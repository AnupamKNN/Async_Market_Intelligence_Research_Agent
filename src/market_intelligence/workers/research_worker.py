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
    DEFAULT_LEASE_DURATION_SECONDS,
    claim_research_job,
    complete_research_job,
    get_research_job,
    heartbeat_research_job,
    initialize_research_jobs,
    retry_research_job,
)
from market_intelligence.mcp.langchain_bridge import MCPToolBridge
from market_intelligence.orchestration.graph import build_research_graph
from market_intelligence.services.research_outbox_publisher import (
    run_outbox_publisher,
)
from market_intelligence.services.research_queue import (
    MAX_MALFORMED_DELIVERIES,
    QUEUE_GROUP,
    QUEUE_STREAM,
    acknowledge_research_message,
    dead_letter_research_message,
    get_pending_delivery_count,
    publish_job_event,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


LEASE_DURATION_SECONDS = DEFAULT_LEASE_DURATION_SECONDS
HEARTBEAT_INTERVAL_SECONDS = max(1, LEASE_DURATION_SECONDS // 3)


class LeaseLostError(RuntimeError):
    """Raised when a worker no longer owns its job lease."""


async def publish_event_best_effort(
    redis: Any,
    job_id: UUID,
    event: str,
    data: dict[str, Any],
) -> None:
    """
    Publish a Redis event without allowing event delivery failure
    to change the authoritative PostgreSQL job state.
    """

    try:
        await publish_job_event(
            redis,
            job_id,
            event,
            data,
        )
    except Exception:
        logger.exception(
            "Unable to publish %s event for job %s. PostgreSQL remains authoritative.",
            event,
            job_id,
        )


async def maintain_job_lease(
    pool: Any,
    job_id: UUID,
    lease_token: UUID,
) -> None:
    """
    Renew the database lease periodically while a job is running.
    """

    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)

        try:
            renewed = await heartbeat_research_job(
                pool,
                job_id,
                lease_token,
                lease_duration_seconds=LEASE_DURATION_SECONDS,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise LeaseLostError(f"Unable to renew lease for job {job_id}.") from exc

        if not renewed:
            raise LeaseLostError(f"Worker no longer owns the lease for job {job_id}.")


async def handle_malformed_queue_message(
    redis: Any,
    message_id: str | bytes,
    fields: dict[Any, Any],
    error: Exception,
) -> None:
    """
    Keep malformed messages pending until their delivery limit is reached.
    Then atomically move them to the dead-letter stream.
    """

    try:
        delivery_count = await get_pending_delivery_count(
            redis,
            message_id,
        )

        if delivery_count is None:
            logger.warning(
                "Malformed message %s is no longer pending.",
                message_id,
            )
            return

        if delivery_count < MAX_MALFORMED_DELIVERIES:
            logger.warning(
                "Malformed message %s has delivery %s/%s. It will remain pending for recovery.",
                message_id,
                delivery_count,
                MAX_MALFORMED_DELIVERIES,
            )
            return

        dead_lettered = await dead_letter_research_message(
            redis,
            message_id,
            fields,
            delivery_count,
            f"{type(error).__name__}: {error}",
        )

        if dead_lettered:
            logger.error(
                "Malformed message %s moved to dead-letter stream after %s deliveries.",
                message_id,
                delivery_count,
            )
        else:
            logger.warning(
                "Malformed message %s could not be dead-lettered because it is no longer pending.",
                message_id,
            )

    except Exception:
        logger.exception(
            "Unable to process malformed queue message %s. It will remain pending for recovery.",
            message_id,
        )


async def maintain_redis_pending_message(
    redis: Any,
    job_id: UUID,
    message_id: str | bytes,
    consumer_name: str,
) -> None:
    """
    Refresh the Redis pending-message idle timer while a job is executing.

    PostgreSQL remains authoritative for job ownership. Redis heartbeat
    failures are logged but do not independently invalidate the job.
    """

    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)

        try:
            claimed_ids = await redis.xclaim(
                QUEUE_STREAM,
                QUEUE_GROUP,
                consumer_name,
                min_idle_time=0,
                message_ids=[message_id],
                justid=True,
            )

            if not claimed_ids:
                logger.warning(
                    "Redis pending message %s for job %s could not be refreshed.",
                    message_id,
                    job_id,
                )

        except Exception:
            logger.exception(
                "Unable to refresh Redis pending message %s for job %s. "
                "PostgreSQL lease remains authoritative.",
                message_id,
                job_id,
            )


async def execute_research_graph(
    job_id: UUID,
    payload: dict[str, Any],
    settings: Settings,
    redis: Any,
) -> dict[str, Any]:
    """
    Execute the LangGraph research workflow and publish progress events.
    """

    async with MCPToolBridge() as bridge:
        graph = build_research_graph(
            bridge.tools,
            settings=settings,
        )

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

                    await publish_event_best_effort(
                        redis,
                        job_id,
                        "progress",
                        {
                            "stage": stage,
                            "message": message,
                        },
                    )

        report = final_state.get("report")

        if not report:
            raise RuntimeError("Research graph completed without generating a report.")

        return {
            "report": report,
            "analyst_findings": final_state.get("analyst_findings"),
            "collector_findings": final_state.get("collector_findings"),
            "evidence_grade": final_state.get("evidence_grade"),
            "quantitative_analysis": final_state.get("quantitative_analysis"),
            "errors": final_state.get("errors", []),
        }


async def execute_with_heartbeat(
    job_id: UUID,
    lease_token: UUID,
    payload: dict[str, Any],
    settings: Settings,
    redis: Any,
    pool: Any,
    message_id: str | bytes | None = None,
    consumer_name: str | None = None,
) -> dict[str, Any]:
    """
    Run the research graph while maintaining its PostgreSQL lease
    and, when available, its Redis pending-message idle timer.

    Losing PostgreSQL lease ownership cancels graph execution.
    Redis heartbeat failures do not override PostgreSQL ownership.
    """

    execution_task = asyncio.create_task(
        execute_research_graph(
            job_id,
            payload,
            settings,
            redis,
        ),
        name=f"research-execution-{job_id}",
    )

    heartbeat_task = asyncio.create_task(
        maintain_job_lease(
            pool,
            job_id,
            lease_token,
        ),
        name=f"research-heartbeat-{job_id}",
    )

    tasks = [
        execution_task,
        heartbeat_task,
    ]

    if message_id is not None:
        if consumer_name is None:
            raise ValueError("consumer_name is required when message_id is provided.")

        redis_heartbeat_task = asyncio.create_task(
            maintain_redis_pending_message(
                redis,
                job_id,
                message_id,
                consumer_name,
            ),
            name=f"redis-pending-heartbeat-{job_id}",
        )

        tasks.append(redis_heartbeat_task)

    try:
        done, _ = await asyncio.wait(
            tasks,
            return_when=asyncio.FIRST_COMPLETED,
        )

        # Prefer the graph result if execution has finished.
        # The conditional database completion still verifies ownership.
        if execution_task in done:
            return execution_task.result()

        # A heartbeat task should never finish normally.
        for task in done:
            task.result()

        raise LeaseLostError(f"A heartbeat stopped unexpectedly for job {job_id}.")

    finally:
        for task in tasks:
            if not task.done():
                task.cancel()

        await asyncio.gather(
            *tasks,
            return_exceptions=True,
        )


async def process_research_job(
    job_id: UUID,
    payload: dict[str, Any],
    settings: Settings,
    redis: Any,
    pool: Any,
    worker_id: str,
    message_id: str | bytes | None = None,
) -> bool:
    """
    Execute a job only after successfully acquiring its database lease.

    Returns:
        True:
            The queue message can be acknowledged.

        False:
            Another worker may own the job, or lease ownership was lost.
            Keep the Redis message pending for future recovery.
    """

    lease_token = await claim_research_job(
        pool,
        job_id,
        worker_id,
        lease_duration_seconds=LEASE_DURATION_SECONDS,
    )

    if lease_token is None:
        # Determine whether the job is active elsewhere or terminal.
        job = await get_research_job(
            pool,
            job_id,
        )

        if job is None:
            logger.error(
                "Queue message references nonexistent job %s.",
                job_id,
            )
            return True

        current_status = job["status"]

        if current_status == "completed":
            await publish_event_best_effort(
                redis,
                job_id,
                "completed",
                {
                    "message": "Research report generated successfully.",
                    "status": "completed",
                },
            )
            return True

        if current_status == "failed":
            await publish_event_best_effort(
                redis,
                job_id,
                "failed",
                {
                    "message": job.get("error") or "Research job failed.",
                    "status": "failed",
                },
            )
            return True

        logger.info(
            "Skipping job %s because it is not currently claimable. Current status: %s",
            job_id,
            current_status,
        )

        # Do not acknowledge a job that may still have an active owner.
        return False

    logger.info(
        "Worker %s acquired job %s, attempt %s.",
        worker_id,
        job_id,
        (await get_research_job(pool, job_id))["attempt_count"],
    )

    try:
        await publish_event_best_effort(
            redis,
            job_id,
            "started",
            {
                "message": "Research execution started.",
                "status": "running",
            },
        )

        result = await execute_with_heartbeat(
            job_id,
            lease_token,
            payload,
            settings,
            redis,
            pool,
            message_id=message_id,
            consumer_name=worker_id,
        )

        persisted = await complete_research_job(
            pool,
            job_id,
            result,
            lease_token=lease_token,
        )

        if not persisted:
            logger.warning(
                "Job %s produced a result but its lease was no longer "
                "valid. The result was not persisted by this worker.",
                job_id,
            )
            return False

        # PostgreSQL completion succeeds independently of event delivery.
        await publish_event_best_effort(
            redis,
            job_id,
            "completed",
            {
                "message": "Research report generated successfully.",
                "status": "completed",
            },
        )

        logger.info(
            "Research job %s completed successfully.",
            job_id,
        )

        return True

    except LeaseLostError:
        logger.warning(
            "Worker %s lost ownership of job %s. Stopping this execution.",
            worker_id,
            job_id,
        )

        return False

    except Exception as exc:
        logger.exception(
            "Research job %s failed during execution.",
            job_id,
        )

        retry_status = await retry_research_job(
            pool,
            job_id,
            f"{type(exc).__name__}: {str(exc)}",
            lease_token=lease_token,
        )

        if retry_status is None:
            logger.warning(
                "Worker %s could not schedule another attempt for job %s "
                "because it no longer owns the lease.",
                worker_id,
                job_id,
            )
            return False

        if retry_status == "queued":
            logger.warning(
                "Research job %s failed on this attempt and has been "
                "returned to the queue for another attempt.",
                job_id,
            )

            # Keep the Redis message pending. XAUTOCLAIM will make it
            # available for another attempt when its idle threshold is met.
            return False

        if retry_status == "failed":
            logger.error(
                "Research job %s exhausted its permitted attempts.",
                job_id,
            )

            await publish_event_best_effort(
                redis,
                job_id,
                "failed",
                {
                    "message": "Research execution failed after exhausting retry attempts.",
                    "status": "failed",
                },
            )

            return True

        logger.error(
            "Unexpected retry status %r for research job %s.",
            retry_status,
            job_id,
        )
        return False


async def run_worker() -> None:
    """Start the research consumer and transactional outbox publisher."""

    settings = Settings()

    redis = create_redis_client(settings)
    pool = None
    publisher_task: asyncio.Task | None = None

    consumer = f"{socket.gethostname()}-{uuid4().hex[:8]}"

    try:
        await redis.ping()

        pool = await create_database_pool(settings)

        # Initialize research jobs, lease migrations and outbox storage.
        await initialize_research_jobs(pool)

        # Initialize the Redis consumer group.
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

        logger.info(
            "Research worker started: %s",
            consumer,
        )

        # Run the outbox publisher independently from the research consumer.
        # Both tasks share the same Redis client and PostgreSQL pool.
        publisher_task = asyncio.create_task(
            run_outbox_publisher(redis, pool),
            name="research-outbox-publisher",
        )

        while True:
            # Recover abandoned Redis pending messages.
            claimed = await redis.xautoclaim(
                QUEUE_STREAM,
                QUEUE_GROUP,
                consumer,
                min_idle_time=LEASE_DURATION_SECONDS * 1000,
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

                        if not isinstance(payload, dict):
                            raise ValueError("Research job payload must be a JSON object.")

                    except (
                        KeyError,
                        ValueError,
                        TypeError,
                        json.JSONDecodeError,
                    ) as exc:
                        logger.exception(
                            "Malformed research queue message %s.",
                            message_id,
                        )

                        await handle_malformed_queue_message(
                            redis,
                            message_id,
                            fields,
                            exc,
                        )

                        continue

                    try:
                        should_acknowledge = await process_research_job(
                            job_id,
                            payload,
                            settings,
                            redis,
                            pool,
                            consumer,
                            message_id=message_id,
                        )

                        if should_acknowledge:
                            acknowledged = await acknowledge_research_message(
                                redis,
                                message_id,
                            )

                            if not acknowledged:
                                logger.warning(
                                    "Queue message %s was already acknowledged "
                                    "or is no longer pending.",
                                    message_id,
                                )

                    except Exception:
                        logger.exception(
                            "Unexpected worker error for queue message %s.",
                            message_id,
                        )
                        # Leave the message pending for recovery.

    finally:
        # Stop the publisher before closing its shared dependencies.
        if publisher_task is not None:
            publisher_task.cancel()

            await asyncio.gather(
                publisher_task,
                return_exceptions=True,
            )

        if pool is not None:
            await pool.close()

        await close_redis_client(redis)


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
