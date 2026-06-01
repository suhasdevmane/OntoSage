"""
SQL Agent - Time-series data queries for Building 1
"""

import sys

sys.path.append("/app")

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from orchestrator.llm_manager import TaskType, llm_manager
from orchestrator.services.adapters.registry import adapter_registry
from orchestrator.services.prompt_builder import get_prompt_builder
from shared.config import settings
from shared.models import ConversationState
from shared.utils import get_logger

logger = get_logger(__name__)


class SQLAgent:
    """Generates and executes SQL queries for time-series data"""

    def __init__(self):
        self.db_config = {
            "host": settings.MYSQL_HOST,
            "port": settings.MYSQL_PORT,
            "user": settings.MYSQL_USER,
            "password": settings.MYSQL_PASSWORD,
            "db": settings.MYSQL_DATABASE,
        }
        # C.2: Dynamic prompt builder for dialect-aware SQL generation
        self._prompt_builder = get_prompt_builder()

    async def generate_and_execute(
        self, state: ConversationState, user_query: str
    ) -> Dict[str, Any]:
        """
        Generate and execute SQL query

        Returns:
            Dict with 'query', 'results', 'formatted_response'
        """
        try:
            # Graceful degradation: check adapter availability
            if not adapter_registry.is_available:
                logger.warning("SQL Agent: No database adapters available")
                return {
                    "success": False,
                    "error": "database_unavailable",
                    "query": None,
                    "results": None,
                    "formatted_response": "The time-series database is currently unavailable.",
                }

            # Step 1: Get database schema
            schema = await self._get_schema()

            # Step 2: Generate SQL query
            sql_query = await self._generate_sql(user_query, schema)

            # Step 3: Execute query
            results = await self._execute_query(sql_query)

            # Step 4: Format results
            formatted = await self._format_results(results, user_query, sql_query)

            return {
                "success": True,
                "query": sql_query,
                "results": {"data": results},
                "formatted_response": formatted,
                "schema": schema,
                "analytics_required": True,  # SQL queries are always data queries
            }

        except Exception as e:
            logger.error(f"SQL generation error: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "query": None,
                "results": {"data": []},
                "formatted_response": (
                    "I wasn't able to query the time-series database for this request. "
                    "This may be because the sensor type you're asking about (e.g. energy meters, "
                    "occupancy counters) isn't monitored in this building. "
                    "The Abacws building actively monitors: temperature, CO₂, humidity, "
                    "air quality (PM1/PM2.5/PM10/TVOC/NO₂), illuminance, and gas sensors. "
                    "Try asking about one of these sensor types instead."
                ),
                "analytics_required": False,
            }

    async def fetch_data_for_uuids(
        self,
        uuids: List[str],
        user_query: str,
        storage_map: Optional[Dict[str, str]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Fetch data for specific UUIDs, respecting storage locations.

        Args:
            uuids: List of sensor UUIDs
            user_query: Original user query (for time filtering)
            storage_map: Dictionary mapping UUID -> Storage Location URI (e.g. "bldg:database1")
            start_date: Start date/time string (ISO or relative)
            end_date: End date/time string (ISO or relative)
        """
        try:
            # Graceful degradation: check adapter availability before doing work
            if not adapter_registry.is_available:
                logger.warning(
                    "SQL Agent: No database adapters available — database is unreachable"
                )
                return {
                    "success": False,
                    "error": "database_unavailable",
                    "query": None,
                    "results": {"data": []},
                    "formatted_response": "The time-series database is currently unavailable. I can still answer questions about the building ontology and metadata.",
                    "analytics_required": False,
                }

            logger.info("=" * 80)
            logger.info("SQL AGENT: Fetching Data for UUIDs")
            logger.info("=" * 80)
            logger.info(f"User Query: {user_query}")
            logger.info(f"UUIDs to fetch: {len(uuids)}")
            for i, uuid in enumerate(uuids, 1):
                storage = storage_map.get(uuid, "N/A") if storage_map else "N/A"
                logger.info(f"   {i}. {uuid} (Storage: {storage})")

            # VALIDATION: Validate UUIDs against DB columns (via adapter registry)
            # Use the first non-null storage URI from the storage_map to route to correct DB
            primary_storage_uri = None
            if storage_map:
                primary_storage_uri = next((v for v in storage_map.values() if v), None)
            valid_uuids = await adapter_registry.get_valid_uuids(uuids, primary_storage_uri)
            missing_uuids = set(uuids) - set(valid_uuids)

            if missing_uuids:
                logger.warning(
                    f"⚠️  {len(missing_uuids)} UUIDs found in Ontology are MISSING in SQL Database."
                )
                # logger.debug(f"Missing: {missing_uuids}")

            if not valid_uuids:
                msg = f"Found {len(uuids)} sensors in metadata, but none exist in the time-series database."
                logger.warning(f"❌ {msg}")
                return {
                    "success": True,
                    "query": "Metadata Check (No Columns)",
                    "results": {"data": []},
                    "formatted_response": msg,
                    "analytics_required": False,
                }

            # Continue with valid UUIDs only
            uuids = valid_uuids

            # Group UUIDs by storage location.
            # _resolve_storage_key extracts the fragment from any URI form:
            #   "bldg:database1"  →  "database1"
            #   "http://...#database4" →  "database4"
            grouped_uuids: Dict[str, List[str]] = {}

            if storage_map:
                for uuid in uuids:
                    storage = storage_map.get(uuid)
                    key = adapter_registry._resolve_storage_key(storage) if storage else "default"
                    grouped_uuids.setdefault(key, []).append(uuid)
            else:
                grouped_uuids["default"] = list(uuids)

            # Cap UUIDs per group — deterministic SQL handles many UUIDs correctly,
            # so we can allow up to 30 sensors per query for broad "all zones" requests.
            _UUID_CAP = 30
            for key in grouped_uuids:
                if len(grouped_uuids[key]) > _UUID_CAP:
                    logger.warning(
                        f"⚠️  Too many UUIDs ({len(grouped_uuids[key])}). Limiting to {_UUID_CAP}."
                    )
                    grouped_uuids[key] = grouped_uuids[key][:_UUID_CAP]

            all_data = []

            # Process each storage group (currently only supporting MySQL/default)
            for storage_key, group_uuids in grouped_uuids.items():
                if not group_uuids:
                    continue

                logger.info(
                    f"Fetching data for {len(group_uuids)} UUIDs from storage: {storage_key}"
                )

                # Phase 2.5: Pick the right adapter for this storage location
                adapter = adapter_registry.get(storage_key)
                schema_text = adapter_registry.get_schema_text(storage_key)
                ts_col = adapter_registry.get_timestamp_column(storage_key)
                dialect_hints = adapter.get_dialect_hints() if adapter else ""

                # Format UUIDs for SQL IN clause
                uuid_list_str = ", ".join([f"'{u}'" for u in group_uuids])

                # For non-SQL adapters (MongoDB, InfluxDB, Redis TS) let the adapter
                # build its own native query string; SQL adapters return None here and
                # fall through to the deterministic SQL builder below.
                native_query = (
                    adapter.build_timeseries_query(
                        uuids=group_uuids,
                        ts_col=ts_col,
                        start_date=start_date,
                        end_date=end_date,
                        limit=1000,
                    )
                    if adapter
                    else None
                )

                # For SQL adapters: build deterministic SQL (no LLM drift).
                deterministic_sql = native_query or self._build_uuid_union_query(
                    group_uuids=group_uuids,
                    ts_col=ts_col,
                    start_date=start_date,
                    end_date=end_date,
                    limit=1000,
                )

                # Construct time context (for LLM fallback)
                time_context = ""
                if start_date:
                    time_context += f"Start Date: {start_date}\n"
                if end_date:
                    time_context += f"End Date: {end_date}\n"
                if not time_context:
                    time_context = self._parse_time_references(user_query)

                prompt = f"""You are a SQL expert. Generate a SQL query to fetch time-series data for specific sensors.

{schema_text}

Target Sensor UUIDs ({len(group_uuids)} total): {uuid_list_str}

Time Context:
{time_context}

User Request Context: "{user_query}"

{dialect_hints}

CRITICAL REQUIREMENTS:
1. The schema shows UUIDs as COLUMN NAMES (wide format). You MUST unpivot them using UNION ALL.
2. The timestamp column is called '{ts_col}' (use this exact name in SELECT and WHERE clauses). Alias it as 'timestamp' in final ORDER BY.
3. For each UUID, generate a SELECT statement and combine with UNION ALL.
4. ALWAYS use '{ts_col}' in SELECT/WHERE, alias 'timestamp' in ORDER BY.
5. DO NOT add LIMIT clauses within individual UNION queries - apply global ORDER BY and LIMIT at the end.
6. For multiple UUIDs, wrap in parentheses and add final ORDER BY timestamp DESC LIMIT 1000.

Return ONLY the SQL query, no markdown, no explanations.
"""
                if deterministic_sql:
                    sql_query = deterministic_sql
                else:
                    sql_query = await llm_manager.generate(prompt)
                    sql_query = sql_query.replace("```sql", "").replace("```", "").strip()

                logger.info(f"\n📝 Generated SQL for UUIDs ({storage_key}):")
                logger.info(f"   {sql_query}")

                logger.info(
                    f"\n⚙️  Executing SQL query via adapter ({adapter.adapter_type.value if adapter else 'unknown'})..."
                )
                if adapter:
                    query_result = await adapter.execute_query(sql_query)
                    results = query_result.data if query_result.success else []
                    if not query_result.success:
                        logger.warning(f"Adapter query failed: {query_result.error}")
                        # Phase 2 — SQL repair loop (no repair for deterministic queries)
                        if not deterministic_sql:
                            results = await self._repair_sql(
                                sql_query=sql_query,
                                error=query_result.error or "query failed",
                                user_query=user_query,
                                schema_text=schema_text,
                                uuid_list_str=uuid_list_str,
                                ts_col=ts_col,
                                dialect_hints=dialect_hints,
                                adapter=adapter,
                            )
                else:
                    logger.error("No adapter available for storage: " + storage_key)
                    results = []

                # AUTO-EXPAND: If 0 rows and user didn't specify an explicit time range,
                # fall back to fetching the most recent available data regardless of date.
                # Treat relative defaults like 'now-1d' as non-explicit
                _is_default_range = not start_date or str(start_date).strip().lower() in (
                    "none",
                    "null",
                    "",
                    "now-1d",
                    "now-24h",
                )
                if not results and _is_default_range:
                    has_explicit_time = any(
                        kw in user_query.lower()
                        for kw in [
                            "today",
                            "yesterday",
                            "last week",
                            "last month",
                            "hour",
                            "day",
                            "week",
                            "month",
                            "year",
                            "since",
                            "before",
                            "after",
                            "between",
                            "from",
                            "until",
                        ]
                    )
                    if not has_explicit_time:
                        logger.warning(
                            "⚠️  0 rows with default time window. Retrying with latest available data..."
                        )
                        # Build a simple fallback query that fetches the most recent rows
                        fallback_parts = []
                        for uuid in group_uuids:
                            fallback_parts.append(
                                f"SELECT Datetime AS timestamp, '{uuid}' AS uuid, "
                                f"`{uuid}` AS value FROM sensor_data "
                                f"WHERE `{uuid}` IS NOT NULL "
                                f"ORDER BY Datetime DESC LIMIT 200"
                            )
                        if len(fallback_parts) == 1:
                            fallback_sql = fallback_parts[0] + ";"
                        else:
                            fallback_sql = (
                                "("
                                + ") UNION ALL (".join(fallback_parts)
                                + ") ORDER BY timestamp DESC LIMIT 1000;"
                            )
                        logger.info(f"📝 Fallback SQL: {fallback_sql[:200]}...")
                        results = await self._execute_query(fallback_sql)
                        if results:
                            logger.info(
                                f"✅ Fallback query returned {len(results)} rows (latest available data)"
                            )

                if results:
                    logger.info(f"✅ Query returned {len(results)} rows")
                    if results:
                        logger.info(f"📊 Sample row: {results[0]}")
                    all_data.extend(results)
                else:
                    logger.warning(f"⚠️  No results returned from query")

            # Standardize output format for Analytics Agent
            # We want a flat list of records: [{"timestamp": "...", "uuid": "...", "value": ...}, ...]
            standardized_data = {"data": all_data}

            formatted = await self._format_results(all_data, user_query, "Multiple Queries")

            return {
                "success": True,
                "query": "Multiple Queries (Storage Aware)",
                "results": standardized_data,  # Standardized JSON for Analytics
                "formatted_response": formatted,
                "analytics_required": True,
            }
        except Exception as e:
            logger.error(f"Fetch data for UUIDs failed: {e}")
            return {"success": False, "error": str(e)}

    async def _get_all_db_columns(self) -> set:
        """Get all column names from the default adapter (for UUID validation)."""
        try:
            adapter = adapter_registry.get()
            if adapter:
                return await adapter.get_columns()
            return set()
        except Exception as e:
            logger.error(f"Failed to get DB columns via adapter: {e}")
            return set()

    async def _get_schema(self) -> str:
        """Get schema text from the default adapter."""
        return adapter_registry.get_schema_text()

    async def _repair_sql(
        self,
        sql_query: str,
        error: str,
        user_query: str,
        schema_text: str,
        uuid_list_str: str,
        ts_col: str,
        dialect_hints: str,
        adapter,
        max_attempts: int = 2,
    ) -> List[Dict[str, Any]]:
        """Phase 2: bounded SQL repair loop — feed error + failed SQL back to LLM."""
        _MAX = max_attempts
        failed_sql = sql_query
        last_error = error

        for attempt in range(1, _MAX + 1):
            repair_prompt = f"""The following SQL query failed with an error.
Fix ONLY the SQL syntax/schema issue; keep the same logical intent.

=== FAILED SQL ===
{failed_sql}

=== DB ERROR ===
{last_error}

=== SCHEMA ===
{schema_text}

=== RULES ===
{dialect_hints}
- Target UUIDs (wide-format columns): {uuid_list_str}
- Timestamp column is '{ts_col}' (use EXACT case).
- Return ONLY the corrected SQL, no explanation."""

            try:
                repaired = await llm_manager.generate(repair_prompt, task_type=TaskType.GENERAL)
                repaired_sql = repaired.replace("```sql", "").replace("```", "").strip()
                query_result = await adapter.execute_query(repaired_sql)
                if query_result.success:
                    logger.info(
                        f"[sql_repair] Recovered on attempt {attempt} — "
                        f"original error: {last_error!r}"
                    )
                    return query_result.data
                last_error = query_result.error or "unknown error"
                failed_sql = repaired_sql
                logger.warning(
                    f"[sql_repair] Attempt {attempt} still failed: {last_error}"
                )
            except Exception as exc:
                logger.warning(f"[sql_repair] Attempt {attempt} exception: {exc}")
                last_error = str(exc)

        logger.warning(f"[sql_repair] All {_MAX} repair attempts exhausted")
        return []

    async def _generate_sql(self, user_query: str, schema: str) -> str:
        """Generate SQL query using LLM with dialect-aware prompts (C.2)."""

        # Parse time references
        time_context = self._parse_time_references(user_query)

        # C.2: Get dialect hints from the active adapter; fall back to MySQL
        try:
            adapter = adapter_registry.get()
            dialect_hints = self._prompt_builder.sql_dialect_hints(adapter)
        except Exception:
            dialect_hints = self._prompt_builder.sql_dialect_hints()

        schema_with_tz = self._prompt_builder.sql_schema_hints(schema)

        sql_prompt = f"""You are a SQL expert for building time-series data.

{schema_with_tz}

=== DIALECT & SYNTAX RULES ===
{dialect_hints}

IMPORTANT: The 'sensor_data' table uses a WIDE format where each sensor UUID is a COLUMN name.
The table has a 'Datetime' column (capital D) and many columns named after sensor UUIDs (e.g., '5dd84aa6...').

Time Context:
{time_context}

User Query: {user_query}

CRITICAL RULES:
1. The timestamp column is 'Datetime' (capital D) - use it in SELECT and WHERE clauses. Use alias 'timestamp' in ORDER BY.
2. Select 'Datetime AS timestamp', the UUID column as 'value', and the UUID as string literal for 'uuid'.
3. Filter by time using 'Datetime' column (NOT 'timestamp').
4. NO AGGREGATION (no AVG, SUM, etc.) - fetch raw rows only.
5. Limit to 1000 rows max.
6. Order by 'timestamp DESC'.

Respond with ONLY the SQL query, no markdown, no explanations."""

        response = await llm_manager.generate(sql_prompt)

        # Extract SQL from response
        sql = self._extract_sql(response)

        logger.info(f"Generated SQL query:\n{sql}")
        return sql

    def _parse_time_references(self, query: str) -> str:
        """Parse time references from natural language"""
        query_lower = query.lower()
        try:
            now = datetime.now(ZoneInfo(settings.BUILDING_TIMEZONE))
        except Exception:
            now = datetime.now()

        time_info = "Current time: " + now.strftime("%Y-%m-%d %H:%M:%S %Z") + "\n"

        if "today" in query_lower:
            start = now.replace(hour=0, minute=0, second=0)
            time_info += f"Today starts at: {start.strftime('%Y-%m-%d %H:%M:%S')}\n"

        if "yesterday" in query_lower:
            yesterday = now - timedelta(days=1)
            time_info += f"Yesterday: {yesterday.strftime('%Y-%m-%d')}\n"

        if "last week" in query_lower:
            week_ago = now - timedelta(days=7)
            time_info += f"One week ago: {week_ago.strftime('%Y-%m-%d %H:%M:%S')}\n"

        if "last month" in query_lower:
            month_ago = now - timedelta(days=30)
            time_info += f"One month ago: {month_ago.strftime('%Y-%m-%d %H:%M:%S')}\n"

        # Extract specific hours/days mentions
        if "hour" in query_lower:
            import re

            match = re.search(r"(\d+)\s*hours?", query_lower)
            if match:
                hours = int(match.group(1))
                time_ago = now - timedelta(hours=hours)
                time_info += f"{hours} hours ago: {time_ago.strftime('%Y-%m-%d %H:%M:%S')}\n"

        return time_info

    def _extract_sql(self, response: str) -> str:
        """Extract SQL query from LLM response"""
        # Remove markdown code blocks
        response = response.replace("```sql", "").replace("```", "").strip()

        # Get first SQL statement
        if ";" in response:
            sql = response.split(";")[0].strip() + ";"
        else:
            sql = response.strip()

        return sql

    def _sanitize_datetime(self, value: Optional[str]) -> Optional[str]:
        """Sanitize datetime strings to avoid SQL injection in deterministic queries."""
        if not value or not isinstance(value, str):
            return None
        v = value.strip()
        # Allow digits, space, T, Z, colon, dash, dot, plus
        import re

        if re.match(r"^[0-9T:\\-\\.Z\\+\\s]+$", v):
            return v
        return None

    def _build_uuid_union_query(
        self,
        group_uuids: List[str],
        ts_col: str,
        start_date: Optional[str],
        end_date: Optional[str],
        limit: int = 1000,
    ) -> str:
        """Build deterministic SQL for UUID columns using UNION ALL."""
        ts_safe = f"`{ts_col}`"
        start = self._sanitize_datetime(start_date)
        end = self._sanitize_datetime(end_date)

        time_clauses = []
        if start:
            time_clauses.append(f"{ts_safe} >= '{start}'")
        elif not end:
            # No bounds at all — default to last 30 days to prevent full table scans
            time_clauses.append(f"{ts_safe} >= DATE_SUB(NOW(), INTERVAL 30 DAY)")
        if end:
            time_clauses.append(f"{ts_safe} <= '{end}'")
        time_filter = " AND ".join(time_clauses)
        if time_filter:
            time_filter = f"{time_filter} AND "

        parts = []
        for uuid in group_uuids:
            parts.append(
                f"SELECT {ts_safe} AS timestamp, '{uuid}' AS uuid, `{uuid}` AS value "
                f"FROM sensor_data WHERE {time_filter}`{uuid}` IS NOT NULL"
            )

        if len(parts) == 1:
            return parts[0] + f" ORDER BY timestamp DESC LIMIT {limit};"
        union = ") UNION ALL (".join(parts)
        return f"({union}) ORDER BY timestamp DESC LIMIT {limit};"

    def validate_sql(self, sql: str) -> bool:
        """
        Validate SQL query for security and safety.
        Returns True if safe, raises ValueError if unsafe.
        """
        sql_upper = sql.upper().strip()

        # 1. Ensure it's a SELECT query
        if (
            not sql_upper.startswith("SELECT")
            and not sql_upper.startswith("WITH")
            and not sql_upper.startswith("(")
        ):
            raise ValueError("Only SELECT queries are allowed.")

        # 2. Check for forbidden keywords (DML/DDL)
        # Note: We check for keyword + space to avoid matching substrings like "UPDATE_TIME"
        forbidden_keywords = [
            "DROP ",
            "DELETE ",
            "INSERT ",
            "UPDATE ",
            "ALTER ",
            "TRUNCATE ",
            "GRANT ",
            "REVOKE ",
            "CREATE ",
            "REPLACE ",
        ]

        for keyword in forbidden_keywords:
            if keyword in sql_upper:
                raise ValueError(f"Forbidden keyword detected: {keyword.strip()}")

        # 3. Check for multiple statements (prevention of stacking queries)
        if ";" in sql:
            # Allow a single trailing semicolon
            if sql.count(";") > 1 or (sql.count(";") == 1 and not sql.strip().endswith(";")):
                raise ValueError("Multiple SQL statements are not allowed.")

        return True

    _SQL_SAFETY_LIMIT = 10000

    @staticmethod
    def _ensure_top_level_limit(sql: str, cap: int) -> str:
        """Ensure a top-level LIMIT exists without duplicating one already there.

        LLM-generated UNION ALL queries sometimes include a LIMIT inside a subquery
        (valid) but then the safety-cap code blindly appended another LIMIT at the end
        (invalid MySQL syntax).  This method checks whether the SQL, after stripping
        trailing whitespace/semicolon, already ends with "LIMIT <n>" at the top level.
        If not, it appends one.
        """
        import re as _re

        stripped = sql.rstrip().rstrip(";").rstrip()
        # Does the statement end with a top-level LIMIT clause?
        if _re.search(r"\bLIMIT\s+\d+\s*$", stripped, _re.IGNORECASE):
            return stripped + ";"
        return stripped + f" LIMIT {cap};"

    async def _execute_query(self, sql: str) -> List[Dict[str, Any]]:
        """Execute SQL query via the adapter registry (delegates to the default/MySQL adapter)."""
        try:
            # Enforce LIMIT safety cap — only add one if no top-level LIMIT already present.
            sql = self._ensure_top_level_limit(sql, self._SQL_SAFETY_LIMIT)

            adapter = adapter_registry.get()
            if not adapter:
                raise RuntimeError("No database adapter available")
            result = await adapter.execute_query(sql)
            if not result.success:
                raise Exception(f"Adapter query failed: {result.error}")
            logger.info(f"SQL query returned {result.row_count} rows")
            return result.data
        except Exception as e:
            logger.error(f"SQL execution error: {e}")
            raise Exception(f"Failed to execute SQL query: {str(e)}")

    async def _format_results(
        self, results: List[Dict[str, Any]], user_query: str, sql_query: str
    ) -> str:
        """Format SQL results into natural language"""

        if not results:
            return "No data found for your query."

        # Convert results to readable format
        result_text = f"Found {len(results)} record(s):\n\n"

        for i, row in enumerate(results[:10], 1):  # Limit to 10 rows
            result_text += f"{i}. "
            for key, value in row.items():
                if isinstance(value, datetime):
                    value = value.strftime("%Y-%m-%d %H:%M:%S")
                result_text += f"{key}: {value} | "
            result_text = result_text.rstrip(" | ") + "\n"

        if len(results) > 10:
            result_text += f"\n... and {len(results) - 10} more records"

        # Generate natural language summary
        summary_prompt = f"""Convert these SQL query results into a natural language response.

User Query: {user_query}

Results:
{result_text}

Generate a concise, natural response that:
1. Directly answers the user's question
2. Highlights key statistics (averages, trends, etc.)
3. Uses clear, non-technical language
4. Mentions the time period if relevant

Response:"""

        try:
            summary = await llm_manager.generate(summary_prompt, task_type=TaskType.GENERAL)
            return summary.strip()
        except Exception as e:
            logger.warning(f"[sql_agent] LLM summary generation failed, returning raw results: {e}")
            return result_text  # Fallback to raw results
