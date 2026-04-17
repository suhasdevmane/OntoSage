# orchestrator/services/adapters/__init__.py
# Export all concrete DatabaseAdapter implementations.
# The registry imports them lazily; this file makes them importable
# from a single location if needed elsewhere.

from orchestrator.services.adapters.mysql_adapter       import MySQLAdapter
from orchestrator.services.adapters.postgresql_adapter  import PostgreSQLAdapter
from orchestrator.services.adapters.timescaledb_adapter import TimescaleDBAdapter
from orchestrator.services.adapters.mongodb_adapter     import MongoDBAdapter
from orchestrator.services.adapters.influxdb_adapter    import InfluxDBAdapter
from orchestrator.services.adapters.sqlite_adapter      import SQLiteAdapter
from orchestrator.services.adapters.cassandra_adapter   import CassandraAdapter
from orchestrator.services.adapters.redis_timeseries_adapter import RedisTimeSeriesAdapter

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
