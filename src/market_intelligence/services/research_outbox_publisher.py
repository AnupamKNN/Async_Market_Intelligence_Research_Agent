import asyncio
import json
import logging
from typing import Any
from uuid import UUID, uuid4

from market_intelligence.db.repositories.research_outbox import (
    claim_pending_outbox_records,
    mark_outbox_record_published,
    reschedule_outbox_record,
)
from market_intelligence.services.research_queue import (
    QUEUE_STREAM,
    publish_job_event,
)

logger = logging.getLogger(__name__)

OUTBOX_BATCH_SIZE = 10
OUTBOX_LEASE_SECONDS = 60
OUTBOX_POLL_INTERVAL_SECONDS = 1

BASE_RETRY_DELAY_SECONDS = 2
MAX_RETRY_DELAY_SECONDS = 300


def calculate_retry_delay(attempts: int) -> int:
    """Return exponential backoff capped at five minutes."""

    if attempts < 1:
        raise ValueError("Attempt count must be positive.")

    return min(
        BASE_RETRY_DELAY_SECONDS * (2 ** min(attempts - 1, 9)),
        MAX_RETRY_DELAY_SECONDS,
    )


async def publish_outbox_batch(
    redis: Any,
    pool: Any,
) -> int:
    """
    Claim and publish one batch of pending outbox records.

    Publication is at-least-once. If Redis accepts an entry but
    PostgreSQL cannot record that publication, the record will
    eventually be retried. Database job leases protect execution
    against duplicate queue deliveries.
    """

    lock_token = uuid4()

    records = await claim_pending_outbox_records(
        pool,
        lock_token,
        batch_size=OUTBOX_BATCH_SIZE,
        lease_duration_seconds=OUTBOX_LEASE_SECONDS,
    )

    for record in records:
        outbox_id = record["id"]
        job_id = record["job_id"]
        payload = record["payload"]
        attempts = record["attempts"]

        try:
            if isinstance(payload, str):
                payload = json.loads(payload)

            if not isinstance(payload, dict):
                raise ValueError(f"Outbox payload for job {job_id} must be a JSON object.")

        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            retry_delay = calculate_retry_delay(attempts)

            await _schedule_retry(
                pool,
                outbox_id,
                lock_token,
                exc,
                retry_delay,
            )

            logger.error(
                "Invalid outbox payload for research job %s. Retry scheduled in %s seconds.",
                job_id,
                retry_delay,
                exc_info=True,
            )
            continue

        # Publish the informational queued event before putting the job
        # into the execution stream. This prevents a fast worker from
        # publishing its started event before the queued event.
        try:
            await publish_job_event(
                redis,
                job_id,
                "queued",
                {"message": "Research job accepted and queued."},
            )
        except Exception:
            # Event delivery is best-effort. It must not prevent
            # the actual research job from being published.
            logger.exception(
                "Unable to publish queued event for research job %s.",
                job_id,
            )

        try:
            # Do not set MAXLEN here. Queue entries must not be trimmed
            # before their consumers acknowledge them.
            await redis.xadd(
                QUEUE_STREAM,
                {
                    "job_id": str(job_id),
                    "payload": json.dumps(
                        payload,
                        ensure_ascii=False,
                        default=str,
                    ),
                },
            )

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            retry_delay = calculate_retry_delay(attempts)

            await _schedule_retry(
                pool,
                outbox_id,
                lock_token,
                exc,
                retry_delay,
            )

            logger.exception(
                "Unable to publish research job %s from outbox record %s. "
                "Retry scheduled in %s seconds.",
                job_id,
                outbox_id,
                retry_delay,
            )
            continue

        # Redis has accepted the message. Now mark the outbox record
        # published in PostgreSQL using the current lock token.
        #
        # If this update fails, the outbox lease eventually expires
        # and publication may happen again. This is intentional:
        # at-least-once delivery is safer than losing a job.
        try:
            published = await mark_outbox_record_published(
                pool,
                outbox_id,
                lock_token,
            )

        except asyncio.CancelledError:
            raise

        except Exception:
            logger.exception(
                "Redis accepted research job %s, but PostgreSQL could not "
                "record outbox publication for record %s. "
                "The record will be retried after lease expiry.",
                job_id,
                outbox_id,
            )
            continue

        if not published:
            logger.warning(
                "Outbox record %s was published to Redis, but its "
                "publication lease was no longer owned.",
                outbox_id,
            )
            continue

        logger.info(
            "Published research job %s from outbox record %s on attempt %s.",
            job_id,
            outbox_id,
            attempts,
        )

    return len(records)


async def _schedule_retry(
    pool: Any,
    outbox_id: int,
    lock_token: UUID,
    error: Exception,
    retry_delay_seconds: int,
) -> None:
    """Release a failed record for a later publication attempt."""

    try:
        rescheduled = await reschedule_outbox_record(
            pool,
            outbox_id,
            lock_token,
            f"{type(error).__name__}: {error}",
            retry_delay_seconds,
        )

        if not rescheduled:
            logger.warning(
                "Could not reschedule outbox record %s because its "
                "publication lease is no longer owned.",
                outbox_id,
            )

    except asyncio.CancelledError:
        raise

    except Exception:
        logger.exception(
            "Unable to reschedule outbox record %s. Its publication lease will expire naturally.",
            outbox_id,
        )


async def run_outbox_publisher(
    redis: Any,
    pool: Any,
) -> None:
    """
    Continuously publish pending outbox records until cancelled.

    Multiple publisher instances are safe because PostgreSQL uses
    FOR UPDATE SKIP LOCKED and individual outbox leases.
    """

    logger.info("Research outbox publisher started.")

    while True:
        try:
            claimed_count = await publish_outbox_batch(
                redis,
                pool,
            )

        except asyncio.CancelledError:
            logger.info("Research outbox publisher shutdown requested.")
            raise

        except Exception:
            logger.exception("Research outbox publisher iteration failed.")
            claimed_count = 0

        if claimed_count == 0:
            await asyncio.sleep(OUTBOX_POLL_INTERVAL_SECONDS)
