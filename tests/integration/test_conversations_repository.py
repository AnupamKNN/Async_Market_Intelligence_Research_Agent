from uuid import uuid4

import pytest

from market_intelligence.core.config import Settings
from market_intelligence.db.pool import create_database_pool
from market_intelligence.db.repositories.auth import (
    create_email_user,
    initialize_auth_tables,
)
from market_intelligence.db.repositories.conversations import (
    ConversationHasRunningJobsError,
    create_research_conversation,
    delete_research_conversation,
    initialize_research_conversations,
    list_conversation_jobs,
    rename_research_conversation,
)
from market_intelligence.db.repositories.research_jobs import (
    create_research_job,
    create_research_job_revision,
    initialize_research_jobs,
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
async def conversation_context(db_pool):
    user_id = uuid4()
    conversation_id = uuid4()

    await create_email_user(
        db_pool,
        user_id,
        f"conversation-{user_id}@example.test",
        "Conversation Test User",
        "test-password-hash",
    )

    await create_research_conversation(
        db_pool,
        conversation_id,
        user_id,
        "Initial conversation",
    )

    yield user_id, conversation_id

    # Remove associated records created during the test.
    await db_pool.execute(
        """
        DELETE FROM research_outbox
        WHERE job_id IN (
            SELECT id FROM research_jobs WHERE user_id = $1
        )
        """,
        user_id,
    )

    await db_pool.execute(
        "DELETE FROM research_jobs WHERE user_id = $1",
        user_id,
    )

    await db_pool.execute(
        "DELETE FROM research_conversations WHERE id = $1",
        conversation_id,
    )

    await db_pool.execute(
        "DELETE FROM users WHERE id = $1",
        user_id,
    )


async def test_rename_research_conversation_persists_title(
    db_pool,
    conversation_context,
):
    user_id, conversation_id = conversation_context

    result = await rename_research_conversation(
        db_pool,
        conversation_id,
        user_id,
        "Quarterly Sales Analysis",
    )

    assert result is not None
    assert result["title"] == "Quarterly Sales Analysis"

    stored_title = await db_pool.fetchval(
        """
        SELECT title
        FROM research_conversations
        WHERE id = $1
        """,
        conversation_id,
    )

    assert stored_title == "Quarterly Sales Analysis"


async def test_delete_conversation_rejects_running_jobs(
    db_pool,
    conversation_context,
):
    user_id, conversation_id = conversation_context
    job_id = uuid4()

    await create_research_job(
        pool=db_pool,
        job_id=job_id,
        payload={"question": "Analyze current sales."},
        user_id=user_id,
        conversation_id=conversation_id,
    )

    await db_pool.execute(
        """
        UPDATE research_jobs
        SET status = 'running'
        WHERE id = $1
        """,
        job_id,
    )

    with pytest.raises(ConversationHasRunningJobsError):
        await delete_research_conversation(
            db_pool,
            conversation_id,
            user_id,
        )

    # The failed deletion must leave both records intact.
    conversation_exists = await db_pool.fetchval(
        """
        SELECT EXISTS(
            SELECT 1 FROM research_conversations WHERE id = $1
        )
        """,
        conversation_id,
    )

    job_exists = await db_pool.fetchval(
        """
        SELECT EXISTS(
            SELECT 1 FROM research_jobs WHERE id = $1
        )
        """,
        job_id,
    )

    assert conversation_exists is True
    assert job_exists is True


async def test_delete_conversation_removes_jobs_and_outbox_records(
    db_pool,
    conversation_context,
):
    user_id, conversation_id = conversation_context
    job_id = uuid4()

    await create_research_job(
        pool=db_pool,
        job_id=job_id,
        payload={"question": "Analyze historical sales."},
        user_id=user_id,
        conversation_id=conversation_id,
    )

    # Completed jobs are eligible for deletion.
    await db_pool.execute(
        """
        UPDATE research_jobs
        SET status = 'completed'
        WHERE id = $1
        """,
        job_id,
    )

    deleted_job_ids = await delete_research_conversation(
        db_pool,
        conversation_id,
        user_id,
    )

    assert deleted_job_ids == [job_id]

    conversation_count = await db_pool.fetchval(
        """
        SELECT COUNT(*)
        FROM research_conversations
        WHERE id = $1
        """,
        conversation_id,
    )

    job_count = await db_pool.fetchval(
        """
        SELECT COUNT(*)
        FROM research_jobs
        WHERE id = $1
        """,
        job_id,
    )

    outbox_count = await db_pool.fetchval(
        """
        SELECT COUNT(*)
        FROM research_outbox
        WHERE job_id = $1
        """,
        job_id,
    )

    assert conversation_count == 0
    assert job_count == 0
    assert outbox_count == 0


async def test_list_conversation_jobs_returns_latest_revision_only(
    db_pool,
    conversation_context,
):
    user_id, conversation_id = conversation_context

    original_job_id = uuid4()
    revised_job_id = uuid4()

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

    await db_pool.execute(
        """
        UPDATE research_jobs
        SET status = 'completed'
        WHERE id = $1
        """,
        original_job_id,
    )

    revision = await create_research_job_revision(
        pool=db_pool,
        new_job_id=revised_job_id,
        original_job_id=original_job_id,
        question="Find the top 200 products.",
        user_id=user_id,
        product_limit=200,
    )

    assert revision is not None
    assert revision[2] == 2

    jobs = await list_conversation_jobs(
        db_pool,
        conversation_id,
        user_id,
    )

    assert len(jobs) == 1
    assert jobs[0]["job_id"] == revised_job_id
    assert jobs[0]["question"] == "Find the top 200 products."
