"""
TimescaleDBAdapter
==================
DatabaseAdapter for TimescaleDB — PostgreSQL with hypertable extension.

Inherits all connection / schema / query logic from PostgreSQLAdapter and
overrides only the dialect hints to expose TimescaleDB-specific functions
(time_bucket, locf, interpolate, first, last) to the SQL-generating LLM.

Standard SQL SELECT queries work identically to PostgreSQL, so no override
of execute_query() or build_timeseries_query() is needed.  The deterministic
SQL builder in sql_agent produces correct SQL for both backends.

Hypertable-aware features available via dialect hints:
    SELECT time_bucket('1 hour', "time") AS bucket,
           AVG(value) AS avg_value
    FROM sensor_data
    WHERE uuid = '...'
      AND "time" >= NOW() - INTERVAL '7 days'
    GROUP BY bucket
    ORDER BY bucket DESC
    LIMIT 168;

Install: pip install asyncpg   (same as PostgreSQL)
"""
import sys
sys.path.append('/app')

from typing import Optional

from orchestrator.services.adapters.postgresql_adapter import PostgreSQLAdapter
from orchestrator.services.database_adapter import AdapterType

class TimescaleDBAdapter(PostgreSQLAdapter):
    """
    TimescaleDB adapter — thin wrapper over PostgreSQLAdapter.
    Re-declares adapter_type and extends dialect hints with hypertable SQL.
    """

    adapter_type = AdapterType.TIMESCALEDB

    def __init__(
        self,
        dsn: Optional[str] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        database: Optional[str] = None,
    ) -> None:
        super().__init__(dsn=dsn, host=host, port=port,
                         user=user, password=password, database=database)

    def get_dialect_hints(self) -> str:
        return (
            "TimescaleDB (PostgreSQL + hypertable extension) dialect rules:\n"
            "- Standard PostgreSQL SQL is fully supported.\n"
            "- Timestamp column: 'time' or 'timestamp' (double-quoted if reserved).\n"
            "- Time functions: NOW(), CURRENT_TIMESTAMP, NOW() - INTERVAL '1 day'.\n"
            "- Use time_bucket() for time-based aggregations:\n"
            "      SELECT time_bucket('1 hour', \"time\") AS bucket, AVG(value)\n"
            "      FROM sensor_data\n"
            "      WHERE uuid = '...' AND \"time\" >= NOW() - INTERVAL '7 days'\n"
            "      GROUP BY bucket ORDER BY bucket DESC;\n"
            "- Useful aggregates: first(value, time), last(value, time),\n"
            "  interpolate(), locf() for gap-filling.\n"
            "- Hypertables partition on the time column — always filter on it.\n"
            "- Default time window: \"time\" >= NOW() - INTERVAL '1 day'\n"
            "- Return ONLY the SQL query, no markdown."
        )
