import asyncio
import json
from uuid import uuid4

import pytest

from market_intelligence.core.config import Settings
from market_intelligence.db.pool import create_database_pool
from market_intelligence.db.repositories import research_jobs
from market_intelligence.db.repositories.auth import (
    create_email_user,
    initialize_auth_tables,
)
from market_intelligence.db.repositories.conversations import (
    create_research_conversation,
    initialize_research_conversations,
)
from market_intelligence.db.repositories.research_jobs import (
    create_research_job,
    create_research_job_revision,
    initialize_research_jobs,
)
from market_intelligence.db.repositories.research_outbox import (
    claim_pending_outbox_records,
    mark_outbox_record_published,
    reschedule_outbox_record,
)


@pytest.fixture
async def db_pool():
    pool = await create_database_pool(Settings())

    try:
        await initialize_auth_tables(pool)
        await initialize_research_jobs(pool)
        await initialize_research_conversations(pool)

        yield pool
    finally:
        await pool.close()


@pytest.fixture
async def job_factory(db_pool):
    created_job_ids = []

    async def create_job():
        job_id = uuid4()

        await create_research_job(
            pool=db_pool,
            job_id=job_id,
            payload={"question": "Test transactional outbox publication."},
            user_id=None,
        )

        created_job_ids.append(job_id)
        return job_id

    yield create_job

    for job_id in created_job_ids:
        await db_pool.execute(
            "DELETE FROM research_jobs WHERE id = $1",
            job_id,
        )


async def test_research_job_and_outbox_are_created_atomically(
    db_pool,
    monkeypatch,
):
    """A failed outbox insert must roll back the research job."""

    job_id = uuid4()

    async def fail_outbox_insert(*args, **kwargs):
        raise RuntimeError("Simulated outbox insert failure.")

    monkeypatch.setattr(
        research_jobs,
        "insert_research_outbox_record",
        fail_outbox_insert,
    )

    with pytest.raises(RuntimeError, match="Simulated outbox insert failure"):
        await create_research_job(
            pool=db_pool,
            job_id=job_id,
            payload={"question": "Atomicity test."},
            user_id=None,
        )

    job_count = await db_pool.fetchval(
        "SELECT COUNT(*) FROM research_jobs WHERE id = $1",
        job_id,
    )

    outbox_count = await db_pool.fetchval(
        "SELECT COUNT(*) FROM research_outbox WHERE job_id = $1",
        job_id,
    )

    assert job_count == 0
    assert outbox_count == 0


async def test_create_research_job_creates_outbox_record(
    db_pool,
    job_factory,
):
    job_id = await job_factory()

    row = await db_pool.fetchrow(
        """
        SELECT
            outbox.job_id,
            outbox.payload,
            outbox.attempts,
            outbox.published_at
        FROM research_outbox AS outbox
        WHERE outbox.job_id = $1
        """,
        job_id,
    )

    assert row is not None
    assert row["job_id"] == job_id
    assert row["attempts"] == 0
    assert row["published_at"] is None

    payload = row["payload"]

    if isinstance(payload, str):
        payload = json.loads(payload)

    assert payload["question"] == "Test transactional outbox publication."


async def test_outbox_claim_and_publish_transition(
    db_pool,
    job_factory,
):
    job_id = await job_factory()
    lock_token = uuid4()

    records = await claim_pending_outbox_records(
        db_pool,
        lock_token,
        batch_size=10,
        lease_duration_seconds=60,
    )

    matching = [record for record in records if record["job_id"] == job_id]

    assert len(matching) == 1
    record = matching[0]

    assert record["attempts"] == 1
    assert record["lock_token"] == lock_token

    # A second publisher cannot claim the locked record.
    second_claim = await claim_pending_outbox_records(
        db_pool,
        uuid4(),
        batch_size=10,
        lease_duration_seconds=60,
    )

    assert all(item["job_id"] != job_id for item in second_claim)

    published = await mark_outbox_record_published(
        db_pool,
        record["id"],
        lock_token,
    )

    assert published is True

    row = await db_pool.fetchrow(
        """
        SELECT published_at, lock_token, locked_until
        FROM research_outbox
        WHERE id = $1
        """,
        record["id"],
    )

    assert row["published_at"] is not None
    assert row["lock_token"] is None
    assert row["locked_until"] is None


async def test_outbox_failed_publication_can_be_retried(
    db_pool,
    job_factory,
):
    job_id = await job_factory()
    first_token = uuid4()

    first_claim = await claim_pending_outbox_records(
        db_pool,
        first_token,
        batch_size=10,
        lease_duration_seconds=60,
    )

    record = next(item for item in first_claim if item["job_id"] == job_id)

    rescheduled = await reschedule_outbox_record(
        db_pool,
        record["id"],
        first_token,
        "Redis connection unavailable.",
        retry_delay_seconds=60,
    )

    assert rescheduled is True

    # The record is not available before its retry deadline.
    immediate_claim = await claim_pending_outbox_records(
        db_pool,
        uuid4(),
        batch_size=10,
        lease_duration_seconds=60,
    )

    assert all(item["job_id"] != job_id for item in immediate_claim)

    # Move its retry deadline into the past for deterministic testing.
    await db_pool.execute(
        """
        UPDATE research_outbox
        SET available_at = NOW() - INTERVAL '1 second'
        WHERE id = $1
        """,
        record["id"],
    )

    second_token = uuid4()

    retry_claim = await claim_pending_outbox_records(
        db_pool,
        second_token,
        batch_size=10,
        lease_duration_seconds=60,
    )

    retried_record = next(item for item in retry_claim if item["job_id"] == job_id)

    assert retried_record["attempts"] == 2
    assert retried_record["lock_token"] == second_token


async def test_concurrent_publishers_claim_distinct_records(
    db_pool,
    job_factory,
):
    first_job = await job_factory()
    second_job = await job_factory()

    first_token = uuid4()
    second_token = uuid4()

    first_batch, second_batch = await asyncio.gather(
        claim_pending_outbox_records(
            db_pool,
            first_token,
            batch_size=1,
        ),
        claim_pending_outbox_records(
            db_pool,
            second_token,
            batch_size=1,
        ),
    )

    first_ids = {item["job_id"] for item in first_batch}
    second_ids = {item["job_id"] for item in second_batch}

    assert first_ids
    assert second_ids
    assert first_ids.isdisjoint(second_ids)

    assert first_ids | second_ids == {
        first_job,
        second_job,
    }


async def test_research_job_revision_persists_updated_product_limit(
    db_pool,
):
    """A revision must preserve the original limit and persist its new limit."""

    user_id = uuid4()
    conversation_id = uuid4()
    original_job_id = uuid4()
    revised_job_id = uuid4()

    job_ids = [original_job_id, revised_job_id]

    try:
        # Create an isolated user.
        await create_email_user(
            db_pool,
            user_id,
            f"revision-{user_id}@example.test",
            "Revision Test User",
            "test-password-hash",
        )

        # Create the owning conversation.
        await create_research_conversation(
            db_pool,
            conversation_id,
            user_id,
            "Product analysis revision test",
        )

        # Create the original research job with a limit of 20.
        await create_research_job(
            pool=db_pool,
            job_id=original_job_id,
            payload={
                "question": "Find the top 20 products.",
                "product_limit": 20,
            },
            user_id=user_id,
            conversation_id=conversation_id,
        )

        # Revisions are allowed only for terminal jobs.
        await db_pool.execute(
            """
            UPDATE research_jobs
            SET status = 'completed'
            WHERE id = $1
            """,
            original_job_id,
        )

        # Create a revision requesting 200 products.
        revision = await create_research_job_revision(
            pool=db_pool,
            new_job_id=revised_job_id,
            original_job_id=original_job_id,
            question="Find the top 200 products.",
            user_id=user_id,
            product_limit=200,
        )

        assert revision is not None

        returned_conversation_id, returned_turn_id, revision_number = revision

        assert returned_conversation_id == conversation_id
        assert returned_turn_id == original_job_id
        assert revision_number == 2

        # Retrieve both persisted job records.
        original_row = await db_pool.fetchrow(
            """
            SELECT request_payload, revision_number, turn_id
            FROM research_jobs
            WHERE id = $1
            """,
            original_job_id,
        )

        revised_row = await db_pool.fetchrow(
            """
            SELECT request_payload, revision_number, turn_id
            FROM research_jobs
            WHERE id = $1
            """,
            revised_job_id,
        )

        assert original_row is not None
        assert revised_row is not None

        original_payload = original_row["request_payload"]
        revised_payload = revised_row["request_payload"]

        if isinstance(original_payload, str):
            original_payload = json.loads(original_payload)

        if isinstance(revised_payload, str):
            revised_payload = json.loads(revised_payload)

        # The original execution must remain unchanged.
        assert original_payload["product_limit"] == 20
        assert original_row["revision_number"] == 1

        # The new execution must contain the revised limit.
        assert revised_payload["product_limit"] == 200
        assert revised_payload["question"] == "Find the top 200 products."
        assert revised_row["revision_number"] == 2
        assert revised_row["turn_id"] == original_row["turn_id"]

        # The outbox must publish the same revised payload.
        outbox_row = await db_pool.fetchrow(
            """
            SELECT payload
            FROM research_outbox
            WHERE job_id = $1
            """,
            revised_job_id,
        )

        assert outbox_row is not None

        outbox_payload = outbox_row["payload"]

        if isinstance(outbox_payload, str):
            outbox_payload = json.loads(outbox_payload)

        assert outbox_payload == revised_payload

    finally:
        # Clean up all records created by this test.
        await db_pool.execute(
            "DELETE FROM research_outbox WHERE job_id = ANY($1::uuid[])",
            job_ids,
        )

        await db_pool.execute(
            "DELETE FROM research_jobs WHERE id = ANY($1::uuid[])",
            job_ids,
        )

        await db_pool.execute(
            "DELETE FROM research_conversations WHERE id = $1",
            conversation_id,
        )

        await db_pool.execute(
            "DELETE FROM users WHERE id = $1",
            user_id,
        )
