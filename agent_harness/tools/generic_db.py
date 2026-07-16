"""
Generic Database Tools - Work with any SQL database.
"""

from sqlalchemy import create_engine, text
from typing import List, Dict, Any, Optional
from agent_harness.tool_registry import tool_registry


@tool_registry.register(category="database")
def generic_db_query(
    connection_string: str,
    query: str,
    params: Optional[Dict[str, Any]] = None,
    query_type: str = "select"
) -> Dict[str, Any]:
    """
    Generic SQL database query - works with PostgreSQL, MySQL, SQLite, etc.

    Args:
        connection_string: SQLAlchemy connection string
        query: SQL query
        params: Query parameters (for parameterized queries)
        query_type: Type of query ('select', 'insert', 'update', 'delete')

    Returns:
        Dict with success status and data/affected_rows
    """
    try:
        # For SQLite, use check_same_thread=False to allow multi-threaded access
        if connection_string.startswith("sqlite"):
            engine = create_engine(
                connection_string,
                pool_pre_ping=True,
                connect_args={"check_same_thread": False, "timeout": 30}
            )
        else:
            engine = create_engine(connection_string, pool_pre_ping=True)

        # Use begin() for automatic transaction management
        with engine.begin() as conn:
            result = conn.execute(text(query), params or {})

            if query_type.lower() == "select":
                rows = result.fetchall()
                data = [dict(row._mapping) for row in rows]
                return {
                    "success": True,
                    "data": data,
                    "row_count": len(data),
                    "error": None
                }
            else:
                # begin() auto-commits on exit
                return {
                    "success": True,
                    "affected_rows": result.rowcount,
                    "error": None
                }

    except Exception as e:
        return {
            "success": False,
            "data": None,
            "error": str(e)
        }


@tool_registry.register(category="database")
def generic_db_write(
    connection_string: str,
    table: str,
    data: Dict[str, Any],
    operation: str = "insert"
) -> Dict[str, Any]:
    """
    Generic database write operation (insert/update).

    Args:
        connection_string: SQLAlchemy connection string
        table: Table name
        data: Data dict (column: value)
        operation: 'insert' or 'update'

    Returns:
        Dict with success status and inserted/updated ID
    """
    try:
        # For SQLite, use check_same_thread=False to allow multi-threaded access
        if connection_string.startswith("sqlite"):
            engine = create_engine(
                connection_string,
                pool_pre_ping=True,
                connect_args={"check_same_thread": False, "timeout": 30}
            )
        else:
            engine = create_engine(connection_string, pool_pre_ping=True)

        # Use begin() for automatic transaction management
        with engine.begin() as conn:
            if operation == "insert":
                columns = ", ".join(data.keys())
                placeholders = ", ".join([f":{k}" for k in data.keys()])

                # SQLite doesn't support RETURNING, use lastrowid instead
                if connection_string.startswith("sqlite"):
                    query = text(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})")
                    result = conn.execute(query, data)
                    inserted_id = result.lastrowid
                else:
                    query = text(f"INSERT INTO {table} ({columns}) VALUES ({placeholders}) RETURNING id")
                    result = conn.execute(query, data)
                    inserted_id = result.fetchone()[0] if result.rowcount > 0 else None

                return {
                    "success": True,
                    "operation": "insert",
                    "id": inserted_id,
                    "error": None
                }

            elif operation == "update":
                if "id" not in data:
                    return {
                        "success": False,
                        "error": "ID required for update operation"
                    }

                set_clause = ", ".join([f"{k} = :{k}" for k in data.keys() if k != "id"])
                query = text(f"UPDATE {table} SET {set_clause} WHERE id = :id")
                result = conn.execute(query, data)

                return {
                    "success": True,
                    "operation": "update",
                    "affected_rows": result.rowcount,
                    "error": None
                }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }