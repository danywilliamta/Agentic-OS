"""
Integration tests for TokenUsageTracker with real PostgreSQL database.
"""

import pytest
import subprocess
import time
import tempfile
import os
from unittest.mock import AsyncMock, patch

from agent_harness.token_tracker import TokenUsageTracker
from agent_harness.agent_factory import AgentFactory


@pytest.fixture(scope="module")
def postgres_container():
    """Start a PostgreSQL container for integration tests."""
    container_name = "test-postgres-token-tracker"

    # Stop and remove container if it exists
    subprocess.run(
        ["docker", "rm", "-f", container_name],
        capture_output=True
    )

    # Start PostgreSQL container
    subprocess.run([
        "docker", "run", "-d",
        "--name", container_name,
        "-e", "POSTGRES_PASSWORD=testpass",
        "-e", "POSTGRES_USER=testuser",
        "-e", "POSTGRES_DB=testdb",
        "-p", "5433:5432",  # Use port 5433 to avoid conflicts
        "postgres:15-alpine"
    ], check=True)

    # Wait for PostgreSQL to be ready
    max_retries = 30
    for i in range(max_retries):
        result = subprocess.run(
            ["docker", "exec", container_name, "pg_isready", "-U", "testuser"],
            capture_output=True
        )
        if result.returncode == 0:
            break
        time.sleep(1)
    else:
        subprocess.run(["docker", "rm", "-f", container_name])
        pytest.fail("PostgreSQL container did not start in time")

    # Extra delay to ensure PostgreSQL is fully ready
    time.sleep(2)

    postgres_url = "postgresql://testuser:testpass@localhost:5433/testdb"

    yield postgres_url

    # Cleanup: stop and remove container
    subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)


@pytest.fixture
async def integration_tracker(postgres_container):
    """Create a tracker with real PostgreSQL connection."""
    tracker = TokenUsageTracker(postgres_container)
    await tracker.setup()

    yield tracker

    # Cleanup: delete all test data
    async with tracker._pool.connection() as conn:
        await conn.execute("DELETE FROM token_usage WHERE agent_id LIKE 'integration-test-%'")

    await tracker.close()


class TestPostgreSQLIntegration:
    """Integration tests with real PostgreSQL database."""

    @pytest.mark.asyncio
    async def test_full_workflow_insert_query(self, integration_tracker):
        """Test complete workflow: insert records and query them."""
        # Insert multiple records with different agents and tenants
        await integration_tracker.log_usage(
            "integration-test-agent-1", "user1", "claude-sonnet-4-6",
            1000, 500, tenant_id="tenant-alpha"
        )
        await integration_tracker.log_usage(
            "integration-test-agent-1", "user2", "claude-sonnet-4-6",
            2000, 1000, tenant_id="tenant-alpha"
        )
        await integration_tracker.log_usage(
            "integration-test-agent-2", "user1", "claude-opus-4-5",
            500, 250, tenant_id="tenant-beta"
        )

        # Query stats for tenant-alpha
        stats = await integration_tracker.get_usage_stats(tenant_id="tenant-alpha")
        assert stats["total_calls"] == 2
        assert stats["total_input_tokens"] == 3000
        assert stats["total_output_tokens"] == 1500
        assert stats["total_cost_usd"] > 0

        # Query top consumers by agent
        top = await integration_tracker.get_top_consumers(group_by="agent_id", limit=10)
        test_agents = [t for t in top if t["agent_id"].startswith("integration-test-")]
        assert len(test_agents) >= 2

    @pytest.mark.asyncio
    async def test_concurrent_inserts(self, integration_tracker):
        """Test concurrent writes to PostgreSQL."""
        import asyncio

        # Simulate concurrent usage logging
        tasks = []
        for i in range(10):
            task = integration_tracker.log_usage(
                f"integration-test-concurrent-{i}",
                f"user{i}",
                "claude-haiku-4-5",
                100,
                50
            )
            tasks.append(task)

        # Execute all concurrently
        await asyncio.gather(*tasks)

        # Verify all were inserted
        stats = await integration_tracker.get_usage_stats()
        # Should have at least 10 calls from our test
        assert stats["total_calls"] >= 10

    @pytest.mark.asyncio
    async def test_metadata_storage_and_retrieval(self, integration_tracker):
        """Test that JSONB metadata is correctly stored and retrieved."""
        metadata = {
            "session_id": "abc123",
            "features_used": ["search", "summarize"],
            "performance_ms": 1234,
            "nested": {"key": "value"}
        }

        await integration_tracker.log_usage(
            "integration-test-metadata",
            "user1",
            "claude-sonnet-4-6",
            500,
            250,
            metadata=metadata
        )

        # Query directly to verify metadata
        import json
        async with integration_tracker._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT metadata FROM token_usage WHERE agent_id = %s",
                    ("integration-test-metadata",)
                )
                row = await cur.fetchone()

                # psycopg3 automatically decodes JSONB to Python dict
                stored_metadata = row[0] if isinstance(row[0], dict) else json.loads(row[0])
                assert stored_metadata == metadata
                assert stored_metadata["nested"]["key"] == "value"


class TestAgentFactoryIntegration:
    """Integration tests for AgentFactory with token tracking."""

    @pytest.mark.asyncio
    async def test_factory_auto_configures_tracker(self, postgres_container):
        """Test that factory auto-configures token tracker from DATABASE_URL."""
        import os
        # Set DATABASE_URL
        original_url = os.getenv("DATABASE_URL")
        os.environ["DATABASE_URL"] = postgres_container

        try:
            factory = AgentFactory()

            # Verify tracker config was auto-detected
            assert factory._token_tracker_config.get("enabled") is True

        finally:
            # Restore original
            if original_url:
                os.environ["DATABASE_URL"] = original_url
            else:
                os.environ.pop("DATABASE_URL", None)

    @pytest.mark.asyncio
    async def test_agent_tracks_usage_end_to_end(self, postgres_container):
        """Test full agent invocation with mocked LLM and real token tracking."""
        # Create factory with token tracking
        factory = AgentFactory(token_tracker_config={
            "enabled": True,
            "connection_string": postgres_container
        })

        # Create a simple test agent config
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
            f.write("""
agent_id: integration-test-agent-tracked
model:
  name: claude-sonnet-4-6
  temperature: 0.7
system_prompt: "You are a test assistant."
tools: []
checkpointer:
  enabled: false
""")
            config_path = f.name

        try:
            # Create agent
            agent = await factory.create_from_file(config_path)

            # Verify tracker is configured
            assert agent.token_tracker is not None
            assert isinstance(agent.token_tracker, TokenUsageTracker)

            # Verify tracker uses the correct connection
            assert agent.token_tracker.connection_string == postgres_container

            # Test logging directly
            await agent.token_tracker.log_usage(
                agent_id="integration-test-agent-tracked",
                user_id="integration-test-user",
                model="claude-sonnet-4-6",
                input_tokens=100,
                output_tokens=50
            )

            # Verify usage was logged to database
            stats = await agent.token_tracker.get_usage_stats(
                agent_id="integration-test-agent-tracked"
            )
            assert stats["total_calls"] == 1
            assert stats["total_input_tokens"] == 100
            assert stats["total_output_tokens"] == 50

        finally:
            # Cleanup
            os.unlink(config_path)
            if agent.token_tracker:
                # Delete test data
                async with agent.token_tracker._pool.connection() as conn:
                    await conn.execute(
                        "DELETE FROM token_usage WHERE agent_id = %s",
                        ("integration-test-agent-tracked",)
                    )
                await agent.token_tracker.close()


class TestMultiTenantIntegration:
    """Integration tests for multi-tenant token tracking."""

    @pytest.mark.asyncio
    async def test_tenant_isolation(self, integration_tracker):
        """Test that tenant_id properly isolates usage data."""
        # Create usage for multiple tenants
        tenants = ["integration-tenant-1", "integration-tenant-2", "integration-tenant-3"]

        for tenant in tenants:
            for i in range(5):
                await integration_tracker.log_usage(
                    f"integration-test-agent",
                    f"user{i}",
                    "claude-sonnet-4-6",
                    1000,
                    500,
                    tenant_id=tenant
                )

        # Verify each tenant has exactly 5 calls
        for tenant in tenants:
            stats = await integration_tracker.get_usage_stats(tenant_id=tenant)
            assert stats["total_calls"] == 5
            assert stats["total_input_tokens"] == 5000
            assert stats["total_output_tokens"] == 2500

        # Verify top consumers by tenant
        top = await integration_tracker.get_top_consumers(group_by="tenant_id", limit=10)
        test_tenants = [t for t in top if t["tenant_id"].startswith("integration-tenant-")]
        assert len(test_tenants) == 3

        # All should have same cost since same usage
        costs = [t["total_cost_usd"] for t in test_tenants]
        assert all(abs(c - costs[0]) < 0.0001 for c in costs)


class TestCostCalculationIntegration:
    """Integration tests for cost calculation accuracy."""

    @pytest.mark.asyncio
    async def test_different_models_different_costs(self, integration_tracker):
        """Test that different models result in different costs."""
        token_count = (1000, 500)  # Same for all

        # Test with different models
        models = [
            ("claude-haiku-4-5", "integration-test-haiku"),
            ("claude-sonnet-4-6", "integration-test-sonnet"),
            ("claude-opus-4-5", "integration-test-opus"),
        ]

        for model, agent_id in models:
            await integration_tracker.log_usage(
                agent_id, "user1", model, token_count[0], token_count[1]
            )

        # Get costs for each
        costs = {}
        for model, agent_id in models:
            stats = await integration_tracker.get_usage_stats(agent_id=agent_id)
            costs[model] = stats["total_cost_usd"]

        # Verify: Haiku < Sonnet < Opus
        assert costs["claude-haiku-4-5"] < costs["claude-sonnet-4-6"]
        assert costs["claude-sonnet-4-6"] < costs["claude-opus-4-5"]

        # Verify actual values (based on pricing)
        # Haiku: 1000 * 0.0008/1K + 500 * 0.004/1K = 0.0008 + 0.002 = 0.0028
        assert abs(costs["claude-haiku-4-5"] - 0.0028) < 0.0001

        # Sonnet: 1000 * 0.003/1K + 500 * 0.015/1K = 0.003 + 0.0075 = 0.0105
        assert abs(costs["claude-sonnet-4-6"] - 0.0105) < 0.0001

        # Opus: 1000 * 0.015/1K + 500 * 0.075/1K = 0.015 + 0.0375 = 0.0525
        assert abs(costs["claude-opus-4-5"] - 0.0525) < 0.0001
