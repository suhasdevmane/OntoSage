# orchestrator/services/adapters/__init__.py
# Export all concrete DatabaseAdapter implementations.
# Each adapter has optional third-party dependencies; imports are guarded so
# that a missing package disables only that adapter, not the whole package.

from orchestrator.services.adapters.mysql_adapter import MySQLAdapter
from orchestrator.services.adapters.postgresql_adapter import PostgreSQLAdapter

try:
    from orchestrator.services.adapters.timescaledb_adapter import TimescaleDBAdapter
except ImportError:
    TimescaleDBAdapter = None  # requires asyncpg (usually installed)

try:
    from orchestrator.services.adapters.mongodb_adapter import MongoDBAdapter
except ImportError:
    MongoDBAdapter = None  # requires motor

try:
    from orchestrator.services.adapters.influxdb_adapter import InfluxDBAdapter
except ImportError:
    InfluxDBAdapter = None  # requires influxdb-client

try:
    from orchestrator.services.adapters.sqlite_adapter import SQLiteAdapter
except ImportError:
    SQLiteAdapter = None  # requires aiosqlite

try:
    from orchestrator.services.adapters.cassandra_adapter import CassandraAdapter
except ImportError:
    CassandraAdapter = None  # requires cassandra-driver

try:
    from orchestrator.services.adapters.redis_timeseries_adapter import (
        RedisTimeSeriesAdapter,
    )
except ImportError:
    RedisTimeSeriesAdapter = None  # requires redis with timeseries support

__all__ = [
    "MySQLAdapter",
    "PostgreSQLAdapter",
    "TimescaleDBAdapter",
    "MongoDBAdapter",
    "InfluxDBAdapter",
    "SQLiteAdapter",
    "CassandraAdapter",
    "RedisTimeSeriesAdapter",
]
