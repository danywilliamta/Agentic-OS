"""
Tests for TokenUsageTracker.
"""

import pytest
import tempfile
import os
from datetime import datetime, timedelta
from decimal import Decimal

from agent_harness.token_tracker import TokenUsageTracker


@pytest.fixture
async def sqlite_tracker():
    """Create a SQLite tracker with temporary database."""
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    temp_file.close()

    tracker = TokenUsageTracker(f"sqlite:///{temp_file.name}")
    await tracker.setup()

    yield tracker

    await tracker.close()
    os.unlink(temp_file.name)


@pytest.fixture
async def postgres_tracker():
    """Create a PostgreSQL tracker (requires DATABASE_URL)."""
    db_url = os.getenv("DATABASE_URL")
    if not db_url or not db_url.startswith("postgresql://"):
        pytest.skip("PostgreSQL DATABASE_URL not available")

    tracker = TokenUsageTracker(db_url)
    await tracker.setup()

    yield tracker

    # Cleanup: delete test data
    if tracker.is_postgres:
        async with tracker._pool.acquire() as conn:
            await conn.execute("DELETE FROM token_usage WHERE agent_id LIKE 'test-%'")

    await tracker.close()


class TestTokenUsageTrackerInit:
    def test_init_with_postgresql_url(self):
        tracker = TokenUsageTracker("postgresql://localhost/test")
        assert tracker.is_postgres is True
        assert tracker.is_sqlite is False

    def test_init_with_sqlite_url(self):
        tracker = TokenUsageTracker("sqlite:///test.db")
        assert tracker.is_postgres is False
        assert tracker.is_sqlite is True

    def test_init_with_invalid_url_raises_error(self):
        with pytest.raises(ValueError, match="Unsupported database"):
            TokenUsageTracker("redis://localhost")


class TestCalculateCost:
    @pytest.fixture
    def tracker(self):
        return TokenUsageTracker("sqlite:///:memory:")

    def test_calculate_cost_claude_sonnet(self, tracker):
        costs = tracker.calculate_cost("claude-sonnet-4-6", 1000, 500)

        # $0.003 per 1K input + $0.015 per 1K output
        assert costs["input_cost"] == Decimal("0.003")
        assert costs["output_cost"] == Decimal("0.0075")
        assert costs["total_cost"] == Decimal("0.0105")

    def test_calculate_cost_claude_opus(self, tracker):
        costs = tracker.calculate_cost("claude-opus-4-5", 1000, 500)

        # $0.015 per 1K input + $0.075 per 1K output
        assert costs["input_cost"] == Decimal("0.015")
        assert costs["output_cost"] == Decimal("0.0375")
        assert costs["total_cost"] == Decimal("0.0525")

    def test_calculate_cost_claude_haiku(self, tracker):
        costs = tracker.calculate_cost("claude-haiku-4-5", 1000, 500)

        # $0.0008 per 1K input + $0.004 per 1K output
        assert costs["input_cost"] == Decimal("0.0008")
        assert costs["output_cost"] == Decimal("0.002")
        assert costs["total_cost"] == Decimal("0.0028")

    def test_calculate_cost_gpt_4o_mini(self, tracker):
        costs = tracker.calculate_cost("gpt-4o-mini", 1000, 500)

        # $0.00015 per 1K input + $0.0006 per 1K output
        assert costs["input_cost"] == Decimal("0.00015")
        assert costs["output_cost"] == Decimal("0.0003")
        assert costs["total_cost"] == Decimal("0.00045")

    def test_calculate_cost_gpt_4o_mini_does_not_fall_back_to_default(self, tracker):
        # Regression guard: before gpt-4o-mini had its own entry, this silently
        # used the "default" (Sonnet) rate — ~20x too expensive. Pin it apart
        # from the default-fallback rate so a future removal of this entry
        # fails loudly here instead of just overstating cost in production.
        default_costs = tracker.calculate_cost("some-unlisted-model", 1000, 500)
        gpt_4o_mini_costs = tracker.calculate_cost("gpt-4o-mini", 1000, 500)

        assert gpt_4o_mini_costs["total_cost"] != default_costs["total_cost"]

    def test_calculate_cost_gpt_4o(self, tracker):
        costs = tracker.calculate_cost("gpt-4o", 1000, 500)

        # $0.0025 per 1K input + $0.01 per 1K output
        assert costs["input_cost"] == Decimal("0.0025")
        assert costs["output_cost"] == Decimal("0.005")
        assert costs["total_cost"] == Decimal("0.0075")

    def test_calculate_cost_gemini_flash_lite_image(self, tracker):
        costs = tracker.calculate_cost("gemini-3.1-flash-lite-image", 1000, 1120)

        # $0.00025 per 1K input + $0.03 per 1K output (image tokens)
        assert costs["input_cost"] == Decimal("0.00025")
        assert costs["output_cost"] == Decimal("0.0336")
        assert costs["total_cost"] == Decimal("0.03385")

    def test_calculate_cost_gemini_image_does_not_fall_back_to_default(self, tracker):
        # Regression guard, same rationale as the gpt-4o-mini one above: image
        # output tokens ($30/1M) are ~2x the "default" Sonnet text rate
        # ($15/1M) — a silent fallback wouldn't even look obviously wrong,
        # just quietly understate real image-generation cost.
        default_costs = tracker.calculate_cost("some-unlisted-model", 1000, 1120)
        gemini_image_costs = tracker.calculate_cost("gemini-3.1-flash-lite-image", 1000, 1120)

        assert gemini_image_costs["total_cost"] != default_costs["total_cost"]

    def test_calculate_cost_strips_provider_prefix(self, tracker):
        costs = tracker.calculate_cost("anthropic:claude-sonnet-4-6", 1000, 500)

        assert costs["total_cost"] == Decimal("0.0105")

    def test_calculate_cost_unknown_model_uses_default(self, tracker):
        costs = tracker.calculate_cost("unknown-model", 1000, 500)

        # Should use default (sonnet pricing)
        assert costs["total_cost"] == Decimal("0.0105")

    def test_calculate_cost_zero_tokens(self, tracker):
        costs = tracker.calculate_cost("claude-sonnet-4-6", 0, 0)

        assert costs["input_cost"] == Decimal("0")
        assert costs["output_cost"] == Decimal("0")
        assert costs["total_cost"] == Decimal("0")


class TestLogUsageSQLite:
    @pytest.mark.asyncio
    async def test_log_usage_inserts_record(self, sqlite_tracker):
        await sqlite_tracker.log_usage(
            agent_id="test-agent",
            user_id="user123",
            model="claude-sonnet-4-6",
            input_tokens=1000,
            output_tokens=500
        )

        # Verify record was inserted
        import aiosqlite
        async with aiosqlite.connect(sqlite_tracker._sqlite_path) as conn:
            async with conn.execute("SELECT * FROM token_usage") as cursor:
                row = await cursor.fetchone()

                assert row is not None
                assert row[2] == "test-agent"  # agent_id
                assert row[3] == "user123"  # user_id
                assert row[6] == 1000  # input_tokens
                assert row[7] == 500  # output_tokens

    @pytest.mark.asyncio
    async def test_log_usage_calculates_cost(self, sqlite_tracker):
        await sqlite_tracker.log_usage(
            agent_id="test-agent",
            user_id="user123",
            model="claude-sonnet-4-6",
            input_tokens=1000,
            output_tokens=500
        )

        import aiosqlite
        async with aiosqlite.connect(sqlite_tracker._sqlite_path) as conn:
            async with conn.execute("SELECT total_cost_usd FROM token_usage") as cursor:
                row = await cursor.fetchone()

                cost = float(row[0])
                assert cost == pytest.approx(0.0105, rel=1e-6)

    @pytest.mark.asyncio
    async def test_log_usage_gemini_image_row_has_correct_cost(self, sqlite_tracker):
        # Closes the gap left by TestCalculateCost's gemini tests above (those
        # call calculate_cost directly, never through log_usage's actual
        # INSERT) — proves the real end-to-end path this ecosystem's
        # generate_image tool relies on (marketing-agency-ia's
        # _track_gemini_usage) writes a real row with the Gemini-specific
        # rate, not a value silently computed from the "default" fallback.
        await sqlite_tracker.log_usage(
            agent_id="generate_image",
            user_id="system",
            model="gemini-3.1-flash-lite-image",
            input_tokens=1000,
            output_tokens=1120,
            tenant_id="ws-1",
        )

        import aiosqlite
        async with aiosqlite.connect(sqlite_tracker._sqlite_path) as conn:
            async with conn.execute(
                "SELECT agent_id, model, input_tokens, output_tokens, total_cost_usd, tenant_id FROM token_usage"
            ) as cursor:
                row = await cursor.fetchone()

        assert row is not None
        assert row[0] == "generate_image"
        assert row[1] == "gemini-3.1-flash-lite-image"
        assert row[2] == 1000
        assert row[3] == 1120
        assert float(row[4]) == pytest.approx(0.03385, rel=1e-6)
        assert row[5] == "ws-1"

    @pytest.mark.asyncio
    async def test_log_usage_with_tenant_id(self, sqlite_tracker):
        await sqlite_tracker.log_usage(
            agent_id="test-agent",
            user_id="user123",
            model="claude-sonnet-4-6",
            input_tokens=100,
            output_tokens=50,
            tenant_id="workspace-abc"
        )

        import aiosqlite
        async with aiosqlite.connect(sqlite_tracker._sqlite_path) as conn:
            async with conn.execute("SELECT tenant_id FROM token_usage") as cursor:
                row = await cursor.fetchone()

                assert row[0] == "workspace-abc"

    @pytest.mark.asyncio
    async def test_log_usage_with_metadata(self, sqlite_tracker):
        await sqlite_tracker.log_usage(
            agent_id="test-agent",
            user_id="user123",
            model="claude-sonnet-4-6",
            input_tokens=100,
            output_tokens=50,
            metadata={"foo": "bar", "count": 42}
        )

        import aiosqlite
        import json
        async with aiosqlite.connect(sqlite_tracker._sqlite_path) as conn:
            async with conn.execute("SELECT metadata FROM token_usage") as cursor:
                row = await cursor.fetchone()

                metadata = json.loads(row[0])
                assert metadata == {"foo": "bar", "count": 42}


class TestGetUsageStatsSQLite:
    @pytest.mark.asyncio
    async def test_get_usage_stats_empty_database(self, sqlite_tracker):
        stats = await sqlite_tracker.get_usage_stats()

        assert stats["total_calls"] == 0
        assert stats["total_tokens"] == 0
        assert stats["total_cost_usd"] == 0.0

    @pytest.mark.asyncio
    async def test_get_usage_stats_aggregates_records(self, sqlite_tracker):
        # Insert multiple records
        await sqlite_tracker.log_usage("test-agent", "user1", "claude-sonnet-4-6", 1000, 500)
        await sqlite_tracker.log_usage("test-agent", "user2", "claude-sonnet-4-6", 2000, 1000)

        stats = await sqlite_tracker.get_usage_stats()

        assert stats["total_calls"] == 2
        assert stats["total_input_tokens"] == 3000
        assert stats["total_output_tokens"] == 1500
        assert stats["total_tokens"] == 4500
        assert stats["total_cost_usd"] == pytest.approx(0.0315, rel=1e-6)  # 0.0105 + 0.021

    @pytest.mark.asyncio
    async def test_get_usage_stats_filters_by_agent_id(self, sqlite_tracker):
        await sqlite_tracker.log_usage("agent-1", "user1", "claude-sonnet-4-6", 1000, 500)
        await sqlite_tracker.log_usage("agent-2", "user1", "claude-sonnet-4-6", 2000, 1000)

        stats = await sqlite_tracker.get_usage_stats(agent_id="agent-1")

        assert stats["total_calls"] == 1
        assert stats["total_input_tokens"] == 1000

    @pytest.mark.asyncio
    async def test_get_usage_stats_filters_by_tenant_id(self, sqlite_tracker):
        await sqlite_tracker.log_usage("agent-1", "user1", "claude-sonnet-4-6", 1000, 500, tenant_id="tenant-a")
        await sqlite_tracker.log_usage("agent-1", "user2", "claude-sonnet-4-6", 2000, 1000, tenant_id="tenant-b")

        stats = await sqlite_tracker.get_usage_stats(tenant_id="tenant-a")

        assert stats["total_calls"] == 1
        assert stats["total_input_tokens"] == 1000

    @pytest.mark.asyncio
    async def test_get_usage_stats_calculates_averages(self, sqlite_tracker):
        await sqlite_tracker.log_usage("test-agent", "user1", "claude-sonnet-4-6", 1000, 500)
        await sqlite_tracker.log_usage("test-agent", "user2", "claude-sonnet-4-6", 2000, 1000)

        stats = await sqlite_tracker.get_usage_stats()

        assert stats["avg_input_tokens"] == pytest.approx(1500.0)
        assert stats["avg_output_tokens"] == pytest.approx(750.0)


class TestGetTopConsumersSQLite:
    @pytest.mark.asyncio
    async def test_get_top_consumers_by_agent_id(self, sqlite_tracker):
        await sqlite_tracker.log_usage("agent-1", "user1", "claude-sonnet-4-6", 5000, 2000)  # $0.045
        await sqlite_tracker.log_usage("agent-2", "user1", "claude-sonnet-4-6", 2000, 1000)  # $0.021
        await sqlite_tracker.log_usage("agent-3", "user1", "claude-sonnet-4-6", 1000, 500)   # $0.0105

        top = await sqlite_tracker.get_top_consumers(group_by="agent_id", limit=2)

        assert len(top) == 2
        assert top[0]["agent_id"] == "agent-1"
        assert top[0]["total_cost_usd"] == pytest.approx(0.045, rel=1e-6)
        assert top[1]["agent_id"] == "agent-2"

    @pytest.mark.asyncio
    async def test_get_top_consumers_by_user_id(self, sqlite_tracker):
        await sqlite_tracker.log_usage("agent-1", "user-1", "claude-sonnet-4-6", 5000, 2000)
        await sqlite_tracker.log_usage("agent-1", "user-2", "claude-sonnet-4-6", 1000, 500)

        top = await sqlite_tracker.get_top_consumers(group_by="user_id")

        assert len(top) == 2
        assert top[0]["user_id"] == "user-1"
        assert top[1]["user_id"] == "user-2"

    @pytest.mark.asyncio
    async def test_get_top_consumers_by_tenant_id(self, sqlite_tracker):
        await sqlite_tracker.log_usage("agent-1", "user-1", "claude-sonnet-4-6", 5000, 2000, tenant_id="tenant-a")
        await sqlite_tracker.log_usage("agent-1", "user-2", "claude-sonnet-4-6", 1000, 500, tenant_id="tenant-b")

        top = await sqlite_tracker.get_top_consumers(group_by="tenant_id")

        assert len(top) == 2
        assert top[0]["tenant_id"] == "tenant-a"

    @pytest.mark.asyncio
    async def test_get_top_consumers_invalid_group_by_raises_error(self, sqlite_tracker):
        with pytest.raises(ValueError, match="Invalid group_by"):
            await sqlite_tracker.get_top_consumers(group_by="invalid_field")

    @pytest.mark.asyncio
    async def test_get_top_consumers_respects_limit(self, sqlite_tracker):
        for i in range(20):
            await sqlite_tracker.log_usage(f"agent-{i}", "user1", "claude-sonnet-4-6", 1000, 500)

        top = await sqlite_tracker.get_top_consumers(group_by="agent_id", limit=5)

        assert len(top) == 5


class TestLogUsagePostgres:
    @pytest.mark.asyncio
    async def test_log_usage_inserts_record(self, postgres_tracker):
        await postgres_tracker.log_usage(
            agent_id="test-agent",
            user_id="user123",
            model="claude-sonnet-4-6",
            input_tokens=1000,
            output_tokens=500
        )

        # Verify record was inserted
        async with postgres_tracker._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT * FROM token_usage WHERE agent_id = %s", ("test-agent",))
                row = await cur.fetchone()

                assert row is not None
                assert row[2] == "test-agent"  # agent_id
                assert row[3] == "user123"  # user_id
                assert row[6] == 1000  # input_tokens
                assert row[7] == 500  # output_tokens

    @pytest.mark.asyncio
    async def test_log_usage_calculates_cost(self, postgres_tracker):
        await postgres_tracker.log_usage(
            agent_id="test-agent",
            user_id="user123",
            model="claude-sonnet-4-6",
            input_tokens=1000,
            output_tokens=500
        )

        async with postgres_tracker._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT total_cost_usd FROM token_usage WHERE agent_id = %s", ("test-agent",))
                row = await cur.fetchone()

                cost = float(row[0])
                assert cost == pytest.approx(0.0105, rel=1e-6)

    @pytest.mark.asyncio
    async def test_log_usage_with_tenant_id(self, postgres_tracker):
        await postgres_tracker.log_usage(
            agent_id="test-agent",
            user_id="user123",
            model="claude-sonnet-4-6",
            input_tokens=100,
            output_tokens=50,
            tenant_id="workspace-abc"
        )

        async with postgres_tracker._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT tenant_id FROM token_usage WHERE agent_id = %s", ("test-agent",))
                row = await cur.fetchone()

                assert row[0] == "workspace-abc"

    @pytest.mark.asyncio
    async def test_log_usage_with_metadata(self, postgres_tracker):
        await postgres_tracker.log_usage(
            agent_id="test-agent",
            user_id="user123",
            model="claude-sonnet-4-6",
            input_tokens=100,
            output_tokens=50,
            metadata={"foo": "bar", "count": 42}
        )

        import json
        async with postgres_tracker._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT metadata FROM token_usage WHERE agent_id = %s", ("test-agent",))
                row = await cur.fetchone()

                metadata = json.loads(row[0])
                assert metadata == {"foo": "bar", "count": 42}


class TestGetUsageStatsPostgres:
    @pytest.mark.asyncio
    async def test_get_usage_stats_empty_database(self, postgres_tracker):
        # Clean any existing test data
        async with postgres_tracker._pool.connection() as conn:
            await conn.execute("DELETE FROM token_usage WHERE agent_id LIKE 'test-%'")

        stats = await postgres_tracker.get_usage_stats()

        assert stats["total_calls"] == 0
        assert stats["total_tokens"] == 0
        assert stats["total_cost_usd"] == 0.0

    @pytest.mark.asyncio
    async def test_get_usage_stats_aggregates_records(self, postgres_tracker):
        # Insert multiple records
        await postgres_tracker.log_usage("test-agent", "user1", "claude-sonnet-4-6", 1000, 500)
        await postgres_tracker.log_usage("test-agent", "user2", "claude-sonnet-4-6", 2000, 1000)

        stats = await postgres_tracker.get_usage_stats()

        assert stats["total_calls"] >= 2  # May have other records
        # Filter to only test-agent
        stats = await postgres_tracker.get_usage_stats(agent_id="test-agent")
        assert stats["total_calls"] == 2
        assert stats["total_input_tokens"] == 3000
        assert stats["total_output_tokens"] == 1500
        assert stats["total_tokens"] == 4500
        assert stats["total_cost_usd"] == pytest.approx(0.0315, rel=1e-6)

    @pytest.mark.asyncio
    async def test_get_usage_stats_filters_by_agent_id(self, postgres_tracker):
        await postgres_tracker.log_usage("test-agent-1", "user1", "claude-sonnet-4-6", 1000, 500)
        await postgres_tracker.log_usage("test-agent-2", "user1", "claude-sonnet-4-6", 2000, 1000)

        stats = await postgres_tracker.get_usage_stats(agent_id="test-agent-1")

        assert stats["total_calls"] == 1
        assert stats["total_input_tokens"] == 1000

    @pytest.mark.asyncio
    async def test_get_usage_stats_filters_by_tenant_id(self, postgres_tracker):
        await postgres_tracker.log_usage("test-agent-1", "user1", "claude-sonnet-4-6", 1000, 500, tenant_id="test-tenant-a")
        await postgres_tracker.log_usage("test-agent-1", "user2", "claude-sonnet-4-6", 2000, 1000, tenant_id="test-tenant-b")

        stats = await postgres_tracker.get_usage_stats(tenant_id="test-tenant-a")

        assert stats["total_calls"] == 1
        assert stats["total_input_tokens"] == 1000


class TestGetTopConsumersPostgres:
    @pytest.mark.asyncio
    async def test_get_top_consumers_by_agent_id(self, postgres_tracker):
        await postgres_tracker.log_usage("test-top-agent-1", "user1", "claude-sonnet-4-6", 5000, 2000)
        await postgres_tracker.log_usage("test-top-agent-2", "user1", "claude-sonnet-4-6", 2000, 1000)
        await postgres_tracker.log_usage("test-top-agent-3", "user1", "claude-sonnet-4-6", 1000, 500)

        top = await postgres_tracker.get_top_consumers(group_by="agent_id", limit=3)

        # Find our test agents in the results
        test_agents = [t for t in top if t["agent_id"].startswith("test-top-agent")]
        assert len(test_agents) >= 2

        # Sort by cost descending
        test_agents.sort(key=lambda x: x["total_cost_usd"], reverse=True)
        assert test_agents[0]["agent_id"] == "test-top-agent-1"
        assert test_agents[0]["total_cost_usd"] == pytest.approx(0.045, rel=1e-6)

    @pytest.mark.asyncio
    async def test_get_top_consumers_by_user_id(self, postgres_tracker):
        await postgres_tracker.log_usage("test-agent", "test-user-1", "claude-sonnet-4-6", 5000, 2000)
        await postgres_tracker.log_usage("test-agent", "test-user-2", "claude-sonnet-4-6", 1000, 500)

        top = await postgres_tracker.get_top_consumers(group_by="user_id")

        test_users = [t for t in top if t["user_id"].startswith("test-user")]
        assert len(test_users) == 2
        test_users.sort(key=lambda x: x["total_cost_usd"], reverse=True)
        assert test_users[0]["user_id"] == "test-user-1"


class TestAgentIntegration:
    """Test token tracking integration in Agent class."""

    @pytest.fixture
    async def mock_tracker(self):
        """Mock tracker that records calls."""
        class MockTracker:
            def __init__(self):
                self.logged_calls = []

            async def log_usage(self, **kwargs):
                self.logged_calls.append(kwargs)

        return MockTracker()

    @pytest.mark.asyncio
    async def test_agent_logs_anthropic_format(self, mock_tracker):
        """Test extraction of input_tokens and output_tokens format."""
        from agent_harness.agent import Agent

        # Create minimal agent
        class FakeDeepAgent:
            checkpointer = None

        agent = Agent(
            agent_id="test-agent",
            deep_agent=FakeDeepAgent(),
            config={"model": {"name": "claude-sonnet-4-6"}},
            token_tracker=mock_tracker
        )

        # Simulate usage logging
        usage = {"input_tokens": 1000, "output_tokens": 500}
        await agent._log_token_usage("user123", "thread-123", usage)

        assert len(mock_tracker.logged_calls) == 1
        call = mock_tracker.logged_calls[0]
        assert call["input_tokens"] == 1000
        assert call["output_tokens"] == 500

    @pytest.mark.asyncio
    async def test_agent_logs_openai_format(self, mock_tracker):
        """Test extraction of prompt_tokens and completion_tokens format."""
        from agent_harness.agent import Agent

        class FakeDeepAgent:
            checkpointer = None

        agent = Agent(
            agent_id="test-agent",
            deep_agent=FakeDeepAgent(),
            config={"model": {"name": "gpt-4"}},
            token_tracker=mock_tracker
        )

        # OpenAI format
        usage = {"prompt_tokens": 1000, "completion_tokens": 500}
        await agent._log_token_usage("user123", "thread-123", usage)

        assert len(mock_tracker.logged_calls) == 1
        call = mock_tracker.logged_calls[0]
        assert call["input_tokens"] == 1000
        assert call["output_tokens"] == 500

    @pytest.mark.asyncio
    async def test_agent_estimates_from_total_tokens(self, mock_tracker):
        """Test fallback estimation when only total_tokens is provided."""
        from agent_harness.agent import Agent

        class FakeDeepAgent:
            checkpointer = None

        agent = Agent(
            agent_id="test-agent",
            deep_agent=FakeDeepAgent(),
            config={"model": {"name": "test-model"}},
            token_tracker=mock_tracker
        )

        # Only total_tokens
        usage = {"total_tokens": 1000}
        await agent._log_token_usage("user123", "thread-123", usage)

        assert len(mock_tracker.logged_calls) == 1
        call = mock_tracker.logged_calls[0]
        # 70/30 split
        assert call["input_tokens"] == 700
        assert call["output_tokens"] == 300

    @pytest.mark.asyncio
    async def test_agent_handles_empty_usage(self, mock_tracker):
        """Test that empty usage doesn't log."""
        from agent_harness.agent import Agent

        class FakeDeepAgent:
            checkpointer = None

        agent = Agent(
            agent_id="test-agent",
            deep_agent=FakeDeepAgent(),
            config={"model": {"name": "test-model"}},
            token_tracker=mock_tracker
        )

        # Empty usage
        usage = {}
        await agent._log_token_usage("user123", "thread-123", usage)

        assert len(mock_tracker.logged_calls) == 0

    @pytest.mark.asyncio
    async def test_agent_handles_invalid_token_types(self, mock_tracker):
        """Test that invalid token values are handled gracefully."""
        from agent_harness.agent import Agent

        class FakeDeepAgent:
            checkpointer = None

        agent = Agent(
            agent_id="test-agent",
            deep_agent=FakeDeepAgent(),
            config={"model": {"name": "test-model"}},
            token_tracker=mock_tracker
        )

        # Invalid types
        usage = {"input_tokens": "not a number", "output_tokens": None}
        await agent._log_token_usage("user123", "thread-123", usage)

        # Should not crash, but also should not log
        assert len(mock_tracker.logged_calls) == 0

    @pytest.mark.asyncio
    async def test_agent_converts_float_tokens_to_int(self, mock_tracker):
        """Test that float token values are converted to int."""
        from agent_harness.agent import Agent

        class FakeDeepAgent:
            checkpointer = None

        agent = Agent(
            agent_id="test-agent",
            deep_agent=FakeDeepAgent(),
            config={"model": {"name": "test-model"}},
            token_tracker=mock_tracker
        )

        # Float tokens
        usage = {"input_tokens": 1000.5, "output_tokens": 500.8}
        await agent._log_token_usage("user123", "thread-123", usage)

        assert len(mock_tracker.logged_calls) == 1
        call = mock_tracker.logged_calls[0]
        assert call["input_tokens"] == 1000
        assert call["output_tokens"] == 500
