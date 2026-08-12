"""
Token Usage Tracker - Track token consumption and costs per user/agent/tenant.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Any
from decimal import Decimal
import json

# PostgreSQL async support (psycopg3 async API)
import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

# SQLite async support
import aiosqlite

logger = logging.getLogger(__name__)


class TokenUsageTracker:
    """
    Track token usage and calculate costs for LLM API calls.

    Supports both PostgreSQL and SQLite backends.
    """

    # Pricing as of August 2026 (USD per 1K tokens)
    # Source: https://www.anthropic.com/pricing
    PRICING = {
        "claude-opus-5": {
            "input": Decimal("0.005"),
            "output": Decimal("0.025"),
        },
        "claude-opus-4-8": {
            "input": Decimal("0.005"),
            "output": Decimal("0.025"),
        },
        "claude-opus-4-7": {
            "input": Decimal("0.005"),
            "output": Decimal("0.025"),
        },
        "claude-opus-4-6": {
            "input": Decimal("0.005"),   # $0.005 per 1K input tokens
            "output": Decimal("0.025"),  # $0.025 per 1K output tokens
        },
        "claude-sonnet-5": {
            # Standard rate — Anthropic runs an intro rate ($0.002/$0.010) through
            # 2026-08-31, deliberately not modeled here (no time-conditional
            # pricing in this table); slightly overstates cost until that date.
            "input": Decimal("0.003"),
            "output": Decimal("0.015"),
        },
        "claude-sonnet-4-6": {
            "input": Decimal("0.003"),   # $0.003 per 1K input tokens
            "output": Decimal("0.015"),  # $0.015 per 1K output tokens
        },
        "claude-sonnet-4-5": {
            "input": Decimal("0.003"),
            "output": Decimal("0.015"),
        },
        "claude-opus-4-5": {
            "input": Decimal("0.015"),   # $0.015 per 1K input tokens
            "output": Decimal("0.075"),  # $0.075 per 1K output tokens
        },
        "claude-haiku-4-5": {
            "input": Decimal("0.001"),   # $0.001 per 1K input tokens
            "output": Decimal("0.005"),  # $0.005 per 1K output tokens
        },
        # OpenAI models — Source: https://platform.openai.com/docs/pricing (rates as
        # known at this package's last update; unlike the Anthropic entries above,
        # not independently reverified against a live August-2026 pricing page —
        # confirm before trusting this table for a real billing/margin decision).
        # Added because callers routing through llm_router's OpenAI path (e.g.
        # this app's brand_brain_importer, EXTRACTOR_MODEL="gpt-4o-mini") were
        # silently falling through to "default" (Sonnet pricing), overstating
        # their real cost by roughly 20x.
        "gpt-4o-mini": {
            "input": Decimal("0.00015"),  # $0.15 per 1M input tokens
            "output": Decimal("0.0006"),  # $0.60 per 1M output tokens
        },
        "gpt-4o": {
            "input": Decimal("0.0025"),  # $2.50 per 1M input tokens
            "output": Decimal("0.01"),   # $10 per 1M output tokens
        },
        # Gemini image generation — Source: https://ai.google.dev/gemini-api/docs/pricing
        # (verified live, August 2026). Output tokens here are dominated by the
        # generated image itself (~1120 tokens/image at 1K resolution), priced at
        # $30/1M — nowhere near the $1.50/1M "output text" rate the same model
        # charges for its accompanying text, and wildly different from any
        # Anthropic/OpenAI entry above. Without this entry, callers logging usage
        # for this model (e.g. this ecosystem's generate_image tool) would fall
        # through to "default" (Sonnet text pricing, $15/1M output) — ~2x too
        # cheap for image output, not just "somewhat off" like the OpenAI gap above.
        "gemini-3.1-flash-lite-image": {
            "input": Decimal("0.00025"),  # $0.25 per 1M input tokens (text/image/video)
            "output": Decimal("0.03"),    # $30.00 per 1M output tokens (image)
        },
        # Embeddings — Source: https://platform.openai.com/docs/pricing (verified
        # live, August 2026). No generation step, so no output tokens — "output"
        # is 0 by construction, not an omission. Previously not logged through
        # this tracker at all (callers never read `response.usage`), so this was
        # a total blind spot rather than a mispriced one, unlike the two entries
        # above — cheap per call ($0.02/1M) but non-trivial in aggregate: fires
        # on every Brand Brain edit, every document upload, and every
        # search_documents tool call.
        "text-embedding-3-small": {
            "input": Decimal("0.00002"),  # $0.02 per 1M input tokens
            "output": Decimal("0"),
        },
        # Fallback for unknown models (use Sonnet pricing) — still wrong for any
        # OpenAI/Gemini model not listed above, just less wrong than no entry at all.
        "default": {
            "input": Decimal("0.003"),
            "output": Decimal("0.015"),
        },
    }

    def __init__(self, connection_string: str):
        """
        Initialize token tracker.

        Args:
            connection_string: Database connection string
                - PostgreSQL: postgresql://user:pass@host:port/db
                - SQLite: sqlite:///path/to/db.db or sqlite:///:memory:
        """
        self.connection_string = connection_string
        self.is_postgres = connection_string.startswith("postgresql://")
        self.is_sqlite = connection_string.startswith("sqlite://")

        if not (self.is_postgres or self.is_sqlite):
            raise ValueError(f"Unsupported database: {connection_string}")

        self._pool = None  # PostgreSQL connection pool
        self._sqlite_path = None  # SQLite file path

        if self.is_sqlite:
            # Extract path from sqlite:///path or sqlite:///:memory:
            self._sqlite_path = connection_string.replace("sqlite:///", "")

    async def setup(self):
        """Initialize database connection and create table if needed."""
        if self.is_postgres:
            # Create async connection pool (psycopg3 async API)
            self._pool = AsyncConnectionPool(self.connection_string, open=False)
            await self._pool.open()
            await self._create_table_postgres()
        elif self.is_sqlite:
            # Create table (connection created per-query)
            await self._create_table_sqlite()

        # Log without exposing full connection string
        db_location = self.connection_string.split('@')[-1] if '@' in self.connection_string else 'local'
        logger.info("TokenUsageTracker initialized: %s", db_location)

    async def _create_table_postgres(self):
        """Create token_usage table in PostgreSQL."""
        async with self._pool.connection() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS token_usage (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    agent_id VARCHAR(255) NOT NULL,
                    user_id VARCHAR(255) NOT NULL,
                    tenant_id VARCHAR(255),
                    model VARCHAR(255) NOT NULL,
                    input_tokens INTEGER NOT NULL,
                    output_tokens INTEGER NOT NULL,
                    total_tokens INTEGER NOT NULL,
                    input_cost_usd DECIMAL(10, 6) NOT NULL,
                    output_cost_usd DECIMAL(10, 6) NOT NULL,
                    total_cost_usd DECIMAL(10, 6) NOT NULL,
                    thread_id VARCHAR(255),
                    metadata JSONB
                );

                -- Indexes for common queries
                CREATE INDEX IF NOT EXISTS idx_token_usage_timestamp
                    ON token_usage(timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_token_usage_agent_id
                    ON token_usage(agent_id);
                CREATE INDEX IF NOT EXISTS idx_token_usage_tenant_id
                    ON token_usage(tenant_id) WHERE tenant_id IS NOT NULL;
                CREATE INDEX IF NOT EXISTS idx_token_usage_user_id
                    ON token_usage(user_id);
            """)
        logger.info("PostgreSQL token_usage table created/verified")

    async def _create_table_sqlite(self):
        """Create token_usage table in SQLite."""
        async with aiosqlite.connect(self._sqlite_path) as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS token_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
                    agent_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    tenant_id TEXT,
                    model TEXT NOT NULL,
                    input_tokens INTEGER NOT NULL,
                    output_tokens INTEGER NOT NULL,
                    total_tokens INTEGER NOT NULL,
                    input_cost_usd REAL NOT NULL,
                    output_cost_usd REAL NOT NULL,
                    total_cost_usd REAL NOT NULL,
                    thread_id TEXT,
                    metadata TEXT
                )
            """)

            # Indexes
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_token_usage_timestamp
                    ON token_usage(timestamp DESC)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_token_usage_agent_id
                    ON token_usage(agent_id)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_token_usage_tenant_id
                    ON token_usage(tenant_id)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_token_usage_user_id
                    ON token_usage(user_id)
            """)

            await conn.commit()
        logger.info("SQLite token_usage table created/verified")

    def calculate_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int
    ) -> Dict[str, Decimal]:
        """
        Calculate cost for token usage.

        Args:
            model: Model name (e.g., 'claude-sonnet-4-6')
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens

        Returns:
            Dict with input_cost, output_cost, total_cost (all in USD)
        """
        # Extract model name from full string (e.g., "anthropic:claude-sonnet-4-6" -> "claude-sonnet-4-6")
        if ":" in model:
            model = model.split(":")[-1]

        # Get pricing (fallback to default if model not found)
        pricing = self.PRICING.get(model, self.PRICING["default"])

        input_cost = (Decimal(input_tokens) / 1000) * pricing["input"]
        output_cost = (Decimal(output_tokens) / 1000) * pricing["output"]
        total_cost = input_cost + output_cost

        return {
            "input_cost": input_cost,
            "output_cost": output_cost,
            "total_cost": total_cost,
        }

    async def log_usage(
        self,
        agent_id: str,
        user_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        tenant_id: Optional[str] = None,
        thread_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        Log token usage to database.

        Args:
            agent_id: Agent identifier
            user_id: User identifier
            model: Model name
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            tenant_id: Optional tenant identifier
            thread_id: Optional thread identifier
            metadata: Optional metadata dict
        """
        # Calculate costs
        costs = self.calculate_cost(model, input_tokens, output_tokens)
        total_tokens = input_tokens + output_tokens

        if self.is_postgres:
            await self._log_usage_postgres(
                agent_id, user_id, tenant_id, model,
                input_tokens, output_tokens, total_tokens,
                costs, thread_id, metadata
            )
        elif self.is_sqlite:
            await self._log_usage_sqlite(
                agent_id, user_id, tenant_id, model,
                input_tokens, output_tokens, total_tokens,
                costs, thread_id, metadata
            )

        logger.info(
            "Token usage logged: agent=%s, user=%s, tenant=%s, model=%s, tokens=%d/%d, cost=$%.4f",
            agent_id,
            user_id,
            tenant_id or "none",
            model,
            input_tokens,
            output_tokens,
            float(costs["total_cost"])
        )

    async def _log_usage_postgres(
        self, agent_id, user_id, tenant_id, model,
        input_tokens, output_tokens, total_tokens,
        costs, thread_id, metadata
    ):
        """Log to PostgreSQL."""
        import json

        async with self._pool.connection() as conn:
            await conn.execute(
                """
                INSERT INTO token_usage (
                    agent_id, user_id, tenant_id, model,
                    input_tokens, output_tokens, total_tokens,
                    input_cost_usd, output_cost_usd, total_cost_usd,
                    thread_id, metadata
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    agent_id, user_id, tenant_id, model,
                    input_tokens, output_tokens, total_tokens,
                    float(costs["input_cost"]),
                    float(costs["output_cost"]),
                    float(costs["total_cost"]),
                    thread_id,
                    json.dumps(metadata) if metadata else None,
                ),
            )

    async def _log_usage_sqlite(
        self, agent_id, user_id, tenant_id, model,
        input_tokens, output_tokens, total_tokens,
        costs, thread_id, metadata
    ):
        """Log to SQLite."""
        import json

        async with aiosqlite.connect(self._sqlite_path) as conn:
            await conn.execute(
                """
                INSERT INTO token_usage (
                    agent_id, user_id, tenant_id, model,
                    input_tokens, output_tokens, total_tokens,
                    input_cost_usd, output_cost_usd, total_cost_usd,
                    thread_id, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    agent_id, user_id, tenant_id, model,
                    input_tokens, output_tokens, total_tokens,
                    float(costs["input_cost"]),
                    float(costs["output_cost"]),
                    float(costs["total_cost"]),
                    thread_id,
                    json.dumps(metadata) if metadata else None,
                ),
            )
            await conn.commit()

    async def get_usage_stats(
        self,
        agent_id: Optional[str] = None,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Get aggregated usage statistics.

        Args:
            agent_id: Filter by agent ID
            user_id: Filter by user ID
            tenant_id: Filter by tenant ID
            since: Start date (default: 30 days ago)
            until: End date (default: now)

        Returns:
            Dict with aggregated stats
        """
        if since is None:
            since = datetime.utcnow() - timedelta(days=30)
        if until is None:
            until = datetime.utcnow()

        if self.is_postgres:
            return await self._get_usage_stats_postgres(
                agent_id, user_id, tenant_id, since, until
            )
        elif self.is_sqlite:
            return await self._get_usage_stats_sqlite(
                agent_id, user_id, tenant_id, since, until
            )

    async def _get_usage_stats_postgres(
        self, agent_id, user_id, tenant_id, since, until
    ) -> Dict[str, Any]:
        """Get stats from PostgreSQL."""
        conditions = ["timestamp >= %s", "timestamp <= %s"]
        params = [since, until]

        if agent_id:
            conditions.append("agent_id = %s")
            params.append(agent_id)
        if user_id:
            conditions.append("user_id = %s")
            params.append(user_id)
        if tenant_id:
            conditions.append("tenant_id = %s")
            params.append(tenant_id)

        where_clause = " AND ".join(conditions)

        async with self._pool.connection() as conn:
            # Use dict_row for dict-like access to results
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    f"""
                    SELECT
                        COUNT(*) as total_calls,
                        SUM(input_tokens) as total_input_tokens,
                        SUM(output_tokens) as total_output_tokens,
                        SUM(total_tokens) as total_tokens,
                        SUM(total_cost_usd) as total_cost_usd,
                        AVG(input_tokens) as avg_input_tokens,
                        AVG(output_tokens) as avg_output_tokens,
                        AVG(total_cost_usd) as avg_cost_per_call
                    FROM token_usage
                    WHERE {where_clause}
                    """,
                    params,
                )
                row = await cur.fetchone()

            return {
                "total_calls": row["total_calls"] or 0,
                "total_input_tokens": row["total_input_tokens"] or 0,
                "total_output_tokens": row["total_output_tokens"] or 0,
                "total_tokens": row["total_tokens"] or 0,
                "total_cost_usd": float(row["total_cost_usd"] or 0),
                "avg_input_tokens": float(row["avg_input_tokens"] or 0),
                "avg_output_tokens": float(row["avg_output_tokens"] or 0),
                "avg_cost_per_call": float(row["avg_cost_per_call"] or 0),
                "period_start": since.isoformat(),
                "period_end": until.isoformat(),
            }

    async def _get_usage_stats_sqlite(
        self, agent_id, user_id, tenant_id, since, until
    ) -> Dict[str, Any]:
        """Get stats from SQLite."""
        conditions = ["timestamp >= ?", "timestamp <= ?"]
        params = [since.isoformat(), until.isoformat()]

        if agent_id:
            conditions.append("agent_id = ?")
            params.append(agent_id)
        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        if tenant_id:
            conditions.append("tenant_id = ?")
            params.append(tenant_id)

        where_clause = " AND ".join(conditions)

        async with aiosqlite.connect(self._sqlite_path) as conn:
            async with conn.execute(
                f"""
                SELECT
                    COUNT(*) as total_calls,
                    SUM(input_tokens) as total_input_tokens,
                    SUM(output_tokens) as total_output_tokens,
                    SUM(total_tokens) as total_tokens,
                    SUM(total_cost_usd) as total_cost_usd,
                    AVG(input_tokens) as avg_input_tokens,
                    AVG(output_tokens) as avg_output_tokens,
                    AVG(total_cost_usd) as avg_cost_per_call
                FROM token_usage
                WHERE {where_clause}
                """,
                params,
            ) as cursor:
                row = await cursor.fetchone()

                return {
                    "total_calls": row[0] or 0,
                    "total_input_tokens": row[1] or 0,
                    "total_output_tokens": row[2] or 0,
                    "total_tokens": row[3] or 0,
                    "total_cost_usd": float(row[4] or 0),
                    "avg_input_tokens": float(row[5] or 0),
                    "avg_output_tokens": float(row[6] or 0),
                    "avg_cost_per_call": float(row[7] or 0),
                    "period_start": since.isoformat(),
                    "period_end": until.isoformat(),
                }

    async def get_top_consumers(
        self,
        group_by: str = "agent_id",
        limit: int = 10,
        since: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get top consumers by cost.

        Args:
            group_by: Group by 'agent_id', 'user_id', or 'tenant_id'
            limit: Number of top consumers to return
            since: Start date (default: 30 days ago)

        Returns:
            List of top consumers with stats
        """
        if since is None:
            since = datetime.utcnow() - timedelta(days=30)

        if group_by not in ["agent_id", "user_id", "tenant_id"]:
            raise ValueError(f"Invalid group_by: {group_by}")

        if self.is_postgres:
            return await self._get_top_consumers_postgres(group_by, limit, since)
        elif self.is_sqlite:
            return await self._get_top_consumers_sqlite(group_by, limit, since)

    async def _get_top_consumers_postgres(
        self, group_by, limit, since
    ) -> List[Dict[str, Any]]:
        """Get top consumers from PostgreSQL."""
        async with self._pool.connection() as conn:
            # Use dict_row for dict-like access to results
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    f"""
                    SELECT
                        {group_by},
                        COUNT(*) as total_calls,
                        SUM(total_tokens) as total_tokens,
                        SUM(total_cost_usd) as total_cost_usd
                    FROM token_usage
                    WHERE timestamp >= %s
                    GROUP BY {group_by}
                    ORDER BY total_cost_usd DESC
                    LIMIT %s
                    """,
                    (since, limit),
                )
                rows = await cur.fetchall()

            return [
                {
                    group_by: row[group_by],
                    "total_calls": row["total_calls"],
                    "total_tokens": row["total_tokens"],
                    "total_cost_usd": float(row["total_cost_usd"]),
                }
                for row in rows
            ]

    async def _get_top_consumers_sqlite(
        self, group_by, limit, since
    ) -> List[Dict[str, Any]]:
        """Get top consumers from SQLite."""
        async with aiosqlite.connect(self._sqlite_path) as conn:
            async with conn.execute(
                f"""
                SELECT
                    {group_by},
                    COUNT(*) as total_calls,
                    SUM(total_tokens) as total_tokens,
                    SUM(total_cost_usd) as total_cost_usd
                FROM token_usage
                WHERE timestamp >= ?
                GROUP BY {group_by}
                ORDER BY total_cost_usd DESC
                LIMIT ?
                """,
                (since.isoformat(), limit),
            ) as cursor:
                rows = await cursor.fetchall()

                return [
                    {
                        group_by: row[0],
                        "total_calls": row[1],
                        "total_tokens": row[2],
                        "total_cost_usd": float(row[3]),
                    }
                    for row in rows
                ]

    async def close(self):
        """Close database connections."""
        if self._pool:
            await self._pool.close()
            logger.info("TokenUsageTracker connections closed")
