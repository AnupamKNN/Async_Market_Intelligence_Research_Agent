import asyncio
import json
import logging
import socket
from typing import Any
from uuid import UUID, uuid4

from redis.exceptions import ResponseError

from market_intelligence.cache.client import (
    close_redis_client,
    create_redis_client,
)
from market_intelligence.core.config import Settings
from market_intelligence.db.pool import create_database_pool
from market_intelligence.db.repositories.research_jobs import (
    complete_research_job,
    fail_research_job,
    initialize_research_jobs,
    mark_job_running,
)
from market_intelligence.mcp.langchain_bridge import MCPToolBridge
from market_intelligence.orchestration.graph import build_research_graph
from market_intelligence.services.research_queue import (
    QUEUE_GROUP,
    QUEUE_STREAM,
    publish_job_event,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


async def process_research_job(
    job_id: UUID,
    payload: dict[str, Any],
    settings: Settings,
    redis: Any,
    pool: Any,
) -> None:
    """Execute one research job and persist its result."""

    try:
        await mark_job_running(pool, job_id)

        await publish_job_event(
            redis,
            job_id,
            "started",
            {"message": "Research execution started."},
        )

        async with MCPToolBridge() as bridge:
            graph = build_research_graph(bridge.tools, settings=settings)

            final_state: dict[str, Any] = {}
            emitted_stages: set[str] = set()

            progress_checks = [
                (
                    "supervisor_decision",
                    "planning",
                    "Research plan prepared.",
                ),
                (
                    "internal_data",
                    "internal_retrieval",
                    "Internal data retrieval completed.",
                ),
                (
                    "external_evidence",
                    "external_retrieval",
                    "External evidence retrieval completed.",
                ),
                (
                    "quantitative_analysis",
                    "quantitative_analysis",
                    "Quantitative analysis completed.",
                ),
                (
                    "collector_findings",
                    "evidence_assessment",
                    "Evidence assessment completed.",
                ),
                (
                    "analyst_findings",
                    "interpretation",
                    "Analytical interpretation completed.",
                ),
            ]

            async for snapshot in graph.astream(
                payload,
                stream_mode="values",
            ):
                final_state = snapshot

                for key, stage, message in progress_checks:
                    if key in snapshot and stage not in emitted_stages:
                        emitted_stages.add(stage)

                        await publish_job_event(
                            redis,
                            job_id,
                            "progress",
                            {"stage": stage, "message": message},
                        )

            report = final_state.get("report")

            if not report:
                raise RuntimeError("Research graph completed without generating a report.")

            result = {
                "report": report,
                "analyst_findings": final_state.get("analyst_findings"),
                "collector_findings": final_state.get("collector_findings"),
                "evidence_grade": final_state.get("evidence_grade"),
                "quantitative_analysis": final_state.get("quantitative_analysis"),
                "errors": final_state.get("errors", []),
            }

            await complete_research_job(pool, job_id, result)

            await publish_job_event(
                redis,
                job_id,
                "completed",
                {
                    "message": "Research report generated successfully.",
                    "status": "completed",
                },
            )

            logger.info("Research job %s completed.", job_id)

    except Exception as exc:
        logger.exception("Research job %s failed.", job_id)

        await fail_research_job(
            pool,
            job_id,
            f"{type(exc).__name__}: {str(exc)}",
        )

        await publish_job_event(
            redis,
            job_id,
            "failed",
            {"message": "Research execution failed. Check worker logs."},
        )


async def run_worker() -> None:
    settings = Settings()
    redis = create_redis_client(settings)
    pool = None

    consumer = f"{socket.gethostname()}-{uuid4().hex[:8]}"

    try:
        await redis.ping()

        pool = await create_database_pool(settings)
        await initialize_research_jobs(pool)

        try:
            await redis.xgroup_create(
                QUEUE_STREAM,
                QUEUE_GROUP,
                id="0",
                mkstream=True,
            )
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

        logger.info("Research worker started: %s", consumer)

        while True:
            # Reclaim jobs abandoned by a worker that crashed.
            claimed = await redis.xautoclaim(
                QUEUE_STREAM,
                QUEUE_GROUP,
                consumer,
                min_idle_time=30 * 60 * 1000,
                start_id="0-0",
                count=1,
            )

            pending_entries = claimed[1]

            if pending_entries:
                entries = [(QUEUE_STREAM, pending_entries)]
            else:
                entries = await redis.xreadgroup(
                    QUEUE_GROUP,
                    consumer,
                    {QUEUE_STREAM: ">"},
                    count=1,
                    block=5000,
                )

            for _, messages in entries:
                for message_id, fields in messages:
                    try:
                        job_id = UUID(fields["job_id"])
                        payload = json.loads(fields["payload"])

                        await process_research_job(
                            job_id,
                            payload,
                            settings,
                            redis,
                            pool,
                        )

                        await redis.xack(
                            QUEUE_STREAM,
                            QUEUE_GROUP,
                            message_id,
                        )

                    except Exception:
                        logger.exception("Failed to process queue message %s.", message_id)

    finally:
        if pool is not None:
            await pool.close()

        await close_redis_client(redis)


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
