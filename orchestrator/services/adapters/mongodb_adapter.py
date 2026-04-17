"""
MongoDBAdapter
==============
DatabaseAdapter for MongoDB time-series collections using motor (async driver).

Query format accepted by execute_query():
    A JSON string with the following optional keys:
    {
        "collection": "sensor_data",       # override default collection
        "filter":     {"uuid": "abc123"},  # PyMongo filter dict
        "projection": {"_id": 0},          # fields to include/exclude
        "sort":       [["timestamp", -1]], # list of [field, direction] pairs
        "limit":      1000
    }

    build_timeseries_query() produces this format automatically.

The dialect_hints tell the LLM exactly what JSON structure to generate when
it needs to query MongoDB directly (e.g., for analytics queries).

Install: pip install motor
"""

import sys

sys.path.append("/app")

import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from orchestrator.services.database_adapter import (
    AdapterType,
    DatabaseAdapter,
    QueryResult,
    SchemaInfo,
)
from shared.utils import get_logger

logger = get_logger(__name__)

_FORBIDDEN_OPS = ["$where", "$function", "$accumulator", "$merge", "$out"]


class MongoDBAdapter(DatabaseAdapter):
    """
    Async MongoDB adapter using motor.
    Expects a collection where each document has at least:
        - a UUID field (string) identifying the sensor
        - a timestamp field (datetime or ISO string)
        - a value field (numeric)

    Example document:
        {
          "uuid": "a8df8757-009a-4997-881b-ba8763219d6e",
          "timestamp": ISODate("2024-01-15T10:30:00Z"),
          "value": 22.5,
          "unit": "degC"
        }
    """

    adapter_type = AdapterType.MONGODB

    def __init__(
        self,
        host: str = "mongodb",
        port: int = 27017,
        user: Optional[str] = None,
        password: Optional[str] = None,
        database: str = "bldg",
        collection: str = "sensor_data",
    ) -> None:
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._database = database
        self._default_collection = collection
        self._client = None
        self._db = None
        self._schema_cache: Optional[SchemaInfo] = None
        self._columns_cache: Optional[Set[str]] = None

    def _build_uri(self) -> str:
        if self._user and self._password:
            return f"mongodb://{self._user}:{self._password}@{self._host}:{self._port}/{self._database}"
        return f"mongodb://{self._host}:{self._port}/{self._database}"

    # ------------------------------------------------------------------
    # DatabaseAdapter interface
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Create a motor AsyncIOMotorClient and test connectivity."""
        try:
            import motor.motor_asyncio as motor

            uri = self._build_uri()
            self._client = motor.AsyncIOMotorClient(uri, serverSelectionTimeoutMS=5000)
            self._db = self._client[self._database]
            # Trigger a round-trip to verify the connection
            await self._client.server_info()
            logger.info(f"MongoDBAdapter: connected to {self._host}:{self._port}/{self._database}")
        except ImportError:
            raise RuntimeError("motor is not installed. Run: pip install motor")
        except Exception as e:
            logger.error(f"MongoDBAdapter: connect failed: {e}")
            raise

    async def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
            self._db = None

    async def get_schema(self) -> SchemaInfo:
        """
        Sample a small number of documents to infer field names.
        MongoDB is schemaless, so we inspect the first 100 documents.
        """
        if self._schema_cache:
            return self._schema_cache

        tables: List[str] = []
        columns: Dict[str, List[tuple]] = {}
        timestamp_col: Optional[str] = None

        try:
            collection_names = await self._db.list_collection_names()
            for coll_name in collection_names:
                tables.append(coll_name)
                col_set: Set[str] = set()
                cursor = self._db[coll_name].find({}, limit=100)
                async for doc in cursor:
                    col_set.update(doc.keys())
                # Detect timestamp field
                for field in ("timestamp", "time", "datetime", "Datetime", "ts", "created_at"):
                    if field in col_set and timestamp_col is None:
                        timestamp_col = field
                col_list = [(f, "any") for f in sorted(col_set)]
                columns[coll_name] = col_list
        except Exception as e:
            logger.error(f"MongoDBAdapter.get_schema failed: {e}")

        self._schema_cache = SchemaInfo(
            tables=tables,
            columns=columns,
            timestamp_column=timestamp_col or "timestamp",
            adapter_type=AdapterType.MONGODB,
        )
        return self._schema_cache

    async def get_columns(self) -> Set[str]:
        """Return all field names found across all collections (for UUID validation)."""
        if self._columns_cache is not None:
            return self._columns_cache

        cols: Set[str] = set()
        try:
            collection_names = await self._db.list_collection_names()
            for coll_name in collection_names:
                cursor = self._db[coll_name].find({}, {"uuid": 1, "_id": 0}, limit=500)
                async for doc in cursor:
                    if "uuid" in doc:
                        cols.add(doc["uuid"])
                # Also add all field names so UUID-validation logic works
                cursor2 = self._db[coll_name].find({}, limit=10)
                async for doc in cursor2:
                    cols.update(doc.keys())
        except Exception as e:
            logger.error(f"MongoDBAdapter.get_columns failed: {e}")

        self._columns_cache = cols
        return cols

    def validate_query(self, query: str) -> bool:
        """
        Safety check: forbid server-side JS and write operations.
        query is expected to be a JSON string.
        """
        for op in _FORBIDDEN_OPS:
            if op in query:
                raise ValueError(f"Forbidden MongoDB operator: {op}")
        return True

    async def execute_query(self, query: str) -> QueryResult:
        """
        Execute a MongoDB query described by a JSON string.

        Expected JSON keys (all optional):
            collection  str   — collection name (default: self._default_collection)
            filter      dict  — PyMongo filter
            projection  dict  — fields to include / exclude
            sort        list  — [[field, direction], ...]  (+1 asc, -1 desc)
            limit       int   — max rows (default 1000)
        """
        try:
            self.validate_query(query)
        except ValueError as e:
            return QueryResult.failure(str(e), query=query)

        try:
            params: Dict[str, Any] = json.loads(query) if query.strip().startswith("{") else {}
        except json.JSONDecodeError as e:
            return QueryResult.failure(f"Invalid JSON query: {e}", query=query)

        coll_name = params.get("collection", self._default_collection)
        flt = params.get("filter", {})
        projection = params.get("projection", {"_id": 0})
        sort_spec = params.get("sort", [["timestamp", -1]])
        limit = int(params.get("limit", 1000))

        try:
            coll = self._db[coll_name]
            cursor = coll.find(flt, projection).sort(sort_spec).limit(limit)
            rows: List[Dict[str, Any]] = []
            async for doc in cursor:
                clean: Dict[str, Any] = {}
                for k, v in doc.items():
                    if isinstance(v, datetime):
                        clean[k] = v.isoformat()
                    elif hasattr(v, "__str__") and not isinstance(
                        v, (int, float, str, bool, type(None))
                    ):
                        clean[k] = str(v)
                    else:
                        clean[k] = v
                rows.append(clean)

            logger.info(f"MongoDBAdapter: {coll_name} returned {len(rows)} documents")
            return QueryResult(success=True, data=rows, row_count=len(rows), query=query)

        except Exception as e:
            logger.error(f"MongoDBAdapter.execute_query error: {e}")
            return QueryResult.failure(str(e), query=query)

    def build_timeseries_query(
        self,
        uuids: List[str],
        ts_col: str,
        start_date: Optional[str],
        end_date: Optional[str],
        limit: int = 1000,
    ) -> Optional[str]:
        """Build a MongoDB JSON query for time-series UUID lookup."""
        flt: Dict[str, Any] = {"uuid": {"$in": uuids}}
        if start_date or end_date:
            time_filter: Dict[str, Any] = {}
            if start_date:
                time_filter["$gte"] = start_date
            if end_date:
                time_filter["$lte"] = end_date
            flt[ts_col] = time_filter

        query_doc = {
            "collection": self._default_collection,
            "filter": flt,
            "projection": {"_id": 0},
            "sort": [[ts_col, -1]],
            "limit": limit,
        }
        return json.dumps(query_doc)

    def get_dialect_hints(self) -> str:
        return (
            "MongoDB query format (JSON string):\n"
            '  {"collection": "sensor_data",\n'
            '   "filter":     {"uuid": {"$in": ["<uuid1>", "<uuid2>"]},\n'
            '                  "timestamp": {"$gte": "2024-01-01", "$lte": "2024-01-07"}},\n'
            '   "projection": {"_id": 0},\n'
            '   "sort":       [["timestamp", -1]],\n'
            '   "limit":      1000}\n'
            "Operators: $in, $gt, $gte, $lt, $lte, $eq, $ne, $and, $or\n"
            "Timestamp field is usually 'timestamp' (ISO string or ISODate).\n"
            "Return ONLY the JSON string, no markdown."
        )
