import asyncio
import json
from uuid import uuid4

import pytest

from market_intelligence.core.config import Settings
from market_intelligence.db.pool import create_database_pool
from market_intelligence.db.repositories.auth import (
    create_email_user,
    initialize_auth_tables,
)
from market_intelligence.db.repositories.research_jobs import (
    cancel_research_job_for_user,
    claim_research_job,
    complete_research_job,
    fail_research_job,
    heartbeat_research_job,
    initialize_research_jobs,
    retry_research_job,
)


@pytest.fixture
async def db_pool():
    """Create a database pool and initialize the required schemas."""

    pool = await create_database_pool(Settings())

    try:
        await initialize_research_jobs(pool)
        await initialize_auth_tables(pool)
        yield pool
    finally:
        await pool.close()

@pytest.fixture
async def user_factory(db_pool):
    """Create isolated users for ownership tests."""

    created_user_ids = []

    async def create_user():
        user_id = uuid4()

        await create_email_user(
            db_pool,
            user_id,
            f"cancellation-{user_id}@example.test",
            "Cancellation Test User",
            "test-password-hash",
        )

        created_user_ids.append(user_id)
        return user_id

    yield create_user

    for user_id in created_user_ids:
        await db_pool.execute(
            "DELETE FROM users WHERE id = $1",
            user_id,
        )

@pytest.fixture
async def job_factory(db_pool):
    """Create isolated research jobs and remove them after each test."""

    created_job_ids = []

    async def create_job(
        max_attempts: int = 3,
        user_id=None,
    ):
        job_id = uuid4()

        await db_pool.execute(
            """
            INSERT INTO research_jobs (
                id,
                question,
                request_payload,
                status,
                max_attempts,
                user_id,
                turn_id,
                revision_number
            )
            VALUES ($1, $2, $3::jsonb, 'queued', $4, $5, $1, 1)
            """,
            job_id,
            "Test research job for worker lease validation.",
            json.dumps({
                "question": "Test research job for worker lease validation."
            }),
            max_attempts,
            user_id,
        )

        created_job_ids.append(job_id)

        return job_id

    yield create_job

    for job_id in created_job_ids:
        await db_pool.execute(
            "DELETE FROM research_jobs WHERE id = $1",
            job_id,
        )


async def expire_job_lease(db_pool, job_id):
    """Force a lease to expire without waiting for the clock."""

    await db_pool.execute(
        """
        UPDATE research_jobs
        SET lease_expires_at = NOW() - INTERVAL '1 second'
        WHERE id = $1
        """,
        job_id,
    )


async def get_job_state(db_pool, job_id):
    """Retrieve job state and normalize PostgreSQL JSONB values."""

    row = await db_pool.fetchrow(
        """
        SELECT
            status,
            attempt_count,
            worker_id,
            lease_token,
            heartbeat_at,
            lease_expires_at,
            error,
            result,
            completed_at
        FROM research_jobs
        WHERE id = $1
        """,
        job_id,
    )

    if row is None:
        return None

    state = dict(row)
    result = state["result"]

    # Handle JSONB returned as a string, including double-encoded JSON.
    while isinstance(result, str):
        try:
            result = json.loads(result)
        except json.JSONDecodeError:
            break

    state["result"] = result

    return state


async def test_only_one_worker_can_claim_a_queued_job(
    db_pool,
    job_factory,
):
    job_id = await job_factory()

    first_token, second_token = await asyncio.gather(
        claim_research_job(db_pool, job_id, "worker-a"),
        claim_research_job(db_pool, job_id, "worker-b"),
    )

    successful_claims = [token for token in (first_token, second_token) if token is not None]

    assert len(successful_claims) == 1

    state = await get_job_state(db_pool, job_id)

    assert state["status"] == "running"
    assert state["attempt_count"] == 1
    assert state["worker_id"] in {"worker-a", "worker-b"}
    assert state["lease_token"] == successful_claims[0]


async def test_another_worker_can_claim_an_expired_lease(
    db_pool,
    job_factory,
):
    job_id = await job_factory()

    first_token = await claim_research_job(
        db_pool,
        job_id,
        "worker-a",
    )

    assert first_token is not None

    await expire_job_lease(db_pool, job_id)

    second_token = await claim_research_job(
        db_pool,
        job_id,
        "worker-b",
    )

    assert second_token is not None
    assert second_token != first_token

    state = await get_job_state(db_pool, job_id)

    assert state["status"] == "running"
    assert state["attempt_count"] == 2
    assert state["worker_id"] == "worker-b"
    assert state["lease_token"] == second_token


async def test_current_worker_can_renew_its_lease(
    db_pool,
    job_factory,
):
    job_id = await job_factory()

    lease_token = await claim_research_job(
        db_pool,
        job_id,
        "worker-a",
    )

    assert lease_token is not None

    renewed = await heartbeat_research_job(
        db_pool,
        job_id,
        lease_token,
    )

    assert renewed is True

    state = await get_job_state(db_pool, job_id)

    assert state["heartbeat_at"] is not None
    assert state["lease_expires_at"] is not None


async def test_worker_with_wrong_token_cannot_renew_lease(
    db_pool,
    job_factory,
):
    job_id = await job_factory()

    lease_token = await claim_research_job(
        db_pool,
        job_id,
        "worker-a",
    )

    assert lease_token is not None

    renewed = await heartbeat_research_job(
        db_pool,
        job_id,
        uuid4(),
    )

    assert renewed is False


async def test_expired_worker_cannot_renew_lease(
    db_pool,
    job_factory,
):
    job_id = await job_factory()

    lease_token = await claim_research_job(
        db_pool,
        job_id,
        "worker-a",
    )

    assert lease_token is not None

    await expire_job_lease(db_pool, job_id)

    renewed = await heartbeat_research_job(
        db_pool,
        job_id,
        lease_token,
    )

    assert renewed is False


async def test_expired_worker_cannot_complete_or_fail_job(
    db_pool,
    job_factory,
):
    job_id = await job_factory()

    old_token = await claim_research_job(
        db_pool,
        job_id,
        "worker-a",
    )

    assert old_token is not None

    await expire_job_lease(db_pool, job_id)

    result = {
        "report": "This result belongs to an expired worker.",
    }

    completed = await complete_research_job(
        db_pool,
        job_id,
        result,
        lease_token=old_token,
    )

    failed = await fail_research_job(
        db_pool,
        job_id,
        "Failure from an expired worker.",
        lease_token=old_token,
    )

    assert completed is False
    assert failed is False

    state = await get_job_state(db_pool, job_id)

    assert state["status"] == "running"
    assert state["result"] is None


async def test_old_worker_cannot_modify_job_after_reclaim(
    db_pool,
    job_factory,
):
    job_id = await job_factory()

    old_token = await claim_research_job(
        db_pool,
        job_id,
        "worker-a",
    )

    assert old_token is not None

    await expire_job_lease(db_pool, job_id)

    new_token = await claim_research_job(
        db_pool,
        job_id,
        "worker-b",
    )

    assert new_token is not None
    assert new_token != old_token

    stale_completion = await complete_research_job(
        db_pool,
        job_id,
        {"report": "Stale result"},
        lease_token=old_token,
    )

    stale_failure = await fail_research_job(
        db_pool,
        job_id,
        "Stale worker failure",
        lease_token=old_token,
    )

    assert stale_completion is False
    assert stale_failure is False

    current_completion = await complete_research_job(
        db_pool,
        job_id,
        {"report": "Valid result"},
        lease_token=new_token,
    )

    assert current_completion is True

    state = await get_job_state(db_pool, job_id)

    assert state["status"] == "completed"
    assert state["result"]["report"] == "Valid result"
    assert state["worker_id"] is None
    assert state["lease_token"] is None


async def test_completed_job_cannot_be_failed(
    db_pool,
    job_factory,
):
    job_id = await job_factory()

    lease_token = await claim_research_job(
        db_pool,
        job_id,
        "worker-a",
    )

    assert lease_token is not None

    completed = await complete_research_job(
        db_pool,
        job_id,
        {"report": "Successful research report"},
        lease_token=lease_token,
    )

    assert completed is True

    failed = await fail_research_job(
        db_pool,
        job_id,
        "Late failure",
    )

    assert failed is False

    state = await get_job_state(db_pool, job_id)

    assert state["status"] == "completed"
    assert state["error"] is None
    assert state["result"]["report"] == "Successful research report"


async def test_maximum_attempts_prevent_another_claim(
    db_pool,
    job_factory,
):
    job_id = await job_factory(max_attempts=1)

    first_token = await claim_research_job(
        db_pool,
        job_id,
        "worker-a",
    )

    assert first_token is not None

    await expire_job_lease(db_pool, job_id)

    second_token = await claim_research_job(
        db_pool,
        job_id,
        "worker-b",
    )

    assert second_token is None

    state = await get_job_state(db_pool, job_id)

    assert state["status"] == "failed"
    assert state["attempt_count"] == 1
    assert state["worker_id"] is None
    assert state["lease_token"] is None
    assert "maximum execution attempts" in state["error"]


async def test_failed_attempt_returns_job_to_queue(
    db_pool,
    job_factory,
):
    job_id = await job_factory(max_attempts=3)

    first_token = await claim_research_job(
        db_pool,
        job_id,
        "worker-a",
    )

    assert first_token is not None

    from market_intelligence.db.repositories.research_jobs import (
        retry_research_job,
    )

    retry_status = await retry_research_job(
        db_pool,
        job_id,
        "Temporary provider failure.",
        first_token,
    )

    assert retry_status == "queued"

    state = await get_job_state(db_pool, job_id)

    assert state["status"] == "queued"
    assert state["attempt_count"] == 1
    assert state["worker_id"] is None
    assert state["lease_token"] is None
    assert state["error"] == "Temporary provider failure."

    # A new worker can claim the released job.
    second_token = await claim_research_job(
        db_pool,
        job_id,
        "worker-b",
    )

    assert second_token is not None
    assert second_token != first_token

    state = await get_job_state(db_pool, job_id)

    assert state["status"] == "running"
    assert state["attempt_count"] == 2
    assert state["worker_id"] == "worker-b"


async def test_retry_exhaustion_marks_job_failed(
    db_pool,
    job_factory,
):
    job_id = await job_factory(max_attempts=2)

    from market_intelligence.db.repositories.research_jobs import (
        retry_research_job,
    )

    first_token = await claim_research_job(
        db_pool,
        job_id,
        "worker-a",
    )

    assert first_token is not None

    first_retry = await retry_research_job(
        db_pool,
        job_id,
        "First attempt failed.",
        first_token,
    )

    assert first_retry == "queued"

    second_token = await claim_research_job(
        db_pool,
        job_id,
        "worker-b",
    )

    assert second_token is not None

    final_status = await retry_research_job(
        db_pool,
        job_id,
        "Second attempt failed.",
        second_token,
    )

    assert final_status == "failed"

    state = await get_job_state(db_pool, job_id)

    assert state["status"] == "failed"
    assert state["attempt_count"] == 2
    assert state["worker_id"] is None
    assert state["lease_token"] is None
    assert state["error"] == "Second attempt failed."
    assert state["completed_at"] is not None

async def test_owner_can_cancel_queued_job(
    db_pool,
    user_factory,
    job_factory,
):
    user_id = await user_factory()
    job_id = await job_factory(user_id=user_id)

    result = await cancel_research_job_for_user(
        db_pool,
        job_id,
        user_id,
    )

    assert result == ("cancelled", True)

    state = await get_job_state(db_pool, job_id)

    assert state["status"] == "cancelled"
    assert state["completed_at"] is not None
    assert state["error"] == "Cancelled by user."
    assert state["worker_id"] is None
    assert state["lease_token"] is None

async def test_owner_can_cancel_running_job_and_invalidate_lease(
    db_pool,
    user_factory,
    job_factory,
):
    user_id = await user_factory()
    job_id = await job_factory(user_id=user_id)

    lease_token = await claim_research_job(
        db_pool,
        job_id,
        "worker-a",
    )

    assert lease_token is not None

    result = await cancel_research_job_for_user(
        db_pool,
        job_id,
        user_id,
    )

    assert result == ("cancelled", True)

    state = await get_job_state(db_pool, job_id)

    assert state["status"] == "cancelled"
    assert state["worker_id"] is None
    assert state["lease_token"] is None
    assert state["heartbeat_at"] is None
    assert state["lease_expires_at"] is None

    # A stale worker must not complete or retry this job.
    completed = await complete_research_job(
        db_pool,
        job_id,
        {"report": "Late result"},
        lease_token=lease_token,
    )

    retried = await retry_research_job(
        db_pool,
        job_id,
        "Late failure",
        lease_token,
    )

    assert completed is False
    assert retried is None

    state = await get_job_state(db_pool, job_id)

    assert state["status"] == "cancelled"
    assert state["result"] is None

async def test_other_user_cannot_cancel_research_job(
    db_pool,
    user_factory,
    job_factory,
):
    owner_id = await user_factory()
    other_user_id = await user_factory()

    job_id = await job_factory(user_id=owner_id)

    result = await cancel_research_job_for_user(
        db_pool,
        job_id,
        other_user_id,
    )

    assert result is None

    state = await get_job_state(db_pool, job_id)

    assert state["status"] == "queued"
    assert state["completed_at"] is None

async def test_completed_job_cannot_be_cancelled(
    db_pool,
    user_factory,
    job_factory,
):
    user_id = await user_factory()
    job_id = await job_factory(user_id=user_id)

    lease_token = await claim_research_job(
        db_pool,
        job_id,
        "worker-a",
    )

    assert lease_token is not None

    completed = await complete_research_job(
        db_pool,
        job_id,
        {"report": "Successfully completed report"},
        lease_token=lease_token,
    )

    assert completed is True

    result = await cancel_research_job_for_user(
        db_pool,
        job_id,
        user_id,
    )

    assert result == ("completed", False)

    state = await get_job_state(db_pool, job_id)

    assert state["status"] == "completed"
    assert state["result"]["report"] == "Successfully completed report"

async def test_repeated_job_cancellation_is_idempotent(
    db_pool,
    user_factory,
    job_factory,
):
    user_id = await user_factory()
    job_id = await job_factory(user_id=user_id)

    first_result = await cancel_research_job_for_user(
        db_pool,
        job_id,
        user_id,
    )

    second_result = await cancel_research_job_for_user(
        db_pool,
        job_id,
        user_id,
    )

    assert first_result == ("cancelled", True)
    assert second_result == ("cancelled", False)

    state = await get_job_state(db_pool, job_id)

    assert state["status"] == "cancelled"