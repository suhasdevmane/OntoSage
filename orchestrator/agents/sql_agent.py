"""
SQL Agent - Time-series data queries for Building 1
"""
import sys
sys.path.append('/app')

import aiomysql
import json
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from shared.models import ConversationState
from shared.utils import get_logger
from shared.config import settings
from orchestrator.llm_manager import llm_manager

logger = get_logger(__name__)

class SQLAgent:
    """Generates and executes SQL queries for time-series data"""
    
    def __init__(self):
        self.db_config = {
            'host': settings.MYSQL_HOST,
            'port': settings.MYSQL_PORT,
            'user': settings.MYSQL_USER,
            'password': settings.MYSQL_PASSWORD,
            'db': settings.MYSQL_DATABASE
        }
    
    async def generate_and_execute(
        self,
        state: ConversationState,
        user_query: str
    ) -> Dict[str, Any]:
        """
        Generate and execute SQL query
        
        Returns:
            Dict with 'query', 'results', 'formatted_response'
        """
        try:
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
                "analytics_required": True  # SQL queries are always data queries
            }
            
        except Exception as e:
            logger.error(f"SQL generation error: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "query": None,
                "results": None
            }
    
    async def fetch_data_for_uuids(
        self,
        uuids: List[str],
        user_query: str,
        storage_map: Optional[Dict[str, str]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
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
            logger.info("="*80)
            logger.info("💾 SQL AGENT: Fetching Data for UUIDs")
            logger.info("="*80)
            logger.info(f"📥 User Query: {user_query}")
            logger.info(f"🔑 UUIDs to fetch: {len(uuids)}")
            for i, uuid in enumerate(uuids, 1):
                storage = storage_map.get(uuid, 'N/A') if storage_map else 'N/A'
                logger.info(f"   {i}. {uuid} (Storage: {storage})")
            
            # Group UUIDs by storage location
            # Default to 'default' if no map provided or storage not found
            grouped_uuids = {"default": []}
            
            if storage_map:
                for uuid in uuids:
                    storage = storage_map.get(uuid)
                    # Normalize storage string (remove prefixes if needed)
                    if storage:
                        if "database1" in storage:
                            key = "database1"
                        else:
                            key = "default" # Fallback to default for now
                    else:
                        key = "default"
                    
                    if key not in grouped_uuids:
                        grouped_uuids[key] = []
                    grouped_uuids[key].append(uuid)
            else:
                grouped_uuids["default"] = uuids
            
            # OPTIMIZATION: If too many UUIDs, limit to first one to avoid SQL truncation
            # This handles cases where user asks for specific sensor but SPARQL returns many matches
            for key in grouped_uuids:
                if len(grouped_uuids[key]) > 3:
                    logger.warning(f"⚠️  Too many UUIDs ({len(grouped_uuids[key])}) from SPARQL. Limiting to first 3 to avoid SQL issues.")
                    logger.warning(f"   User asked for specific sensor, but SPARQL returned multiple matches.")
                    logger.warning(f"   Using UUIDs: {grouped_uuids[key][:3]}")
                    grouped_uuids[key] = grouped_uuids[key][:3]

            all_data = []
            
            # Process each storage group (currently only supporting MySQL/default)
            for storage_key, group_uuids in grouped_uuids.items():
                if not group_uuids:
                    continue
                    
                logger.info(f"Fetching data for {len(group_uuids)} UUIDs from storage: {storage_key}")
                
                # In a fully heterogeneous system, we would switch connection configs here
                # For now, we assume all data is in the configured MySQL DB
                
                schema = await self._get_schema()
                
                # Format UUIDs for SQL IN clause
                uuid_list_str = ", ".join([f"'{u}'" for u in group_uuids])
                
                # Construct time context
                time_context = ""
                if start_date:
                    time_context += f"Start Date: {start_date}\n"
                if end_date:
                    time_context += f"End Date: {end_date}\n"
                if not time_context:
                    time_context = self._parse_time_references(user_query)

                prompt = f"""You are a SQL expert. Generate a MySQL query to fetch time-series data for specific sensors.

Database Schema:
{schema}

Target Sensor UUIDs ({len(group_uuids)} total): {uuid_list_str}

Time Context:
{time_context}

User Request Context: "{user_query}"

CRITICAL REQUIREMENTS:
1. The schema shows UUIDs as COLUMN NAMES (wide format). You MUST unpivot them using UNION ALL.
2. The timestamp column is called 'Datetime' (capital D), NOT 'timestamp'.
3. For each UUID, generate a SELECT statement and combine with UNION ALL.
4. ALWAYS use 'Datetime' as the column name in ALL clauses (SELECT, WHERE, ORDER BY).
5. DO NOT add LIMIT clauses within individual UNION queries - apply global ORDER BY and LIMIT at the end.
6. For multiple UUIDs, wrap in parentheses and add final ORDER BY Datetime DESC LIMIT 1000.

Single UUID Template:
SELECT 
  Datetime AS timestamp, 
  'uuid_value' AS uuid, 
  `uuid_value` AS value
FROM sensor_data
WHERE `uuid_value` IS NOT NULL
  AND [TIME_FILTER_USING_Datetime]
ORDER BY Datetime DESC
LIMIT 1000;

Multiple UUIDs Template:
(
  SELECT Datetime AS timestamp, 'uuid1' AS uuid, `uuid1` AS value
  FROM sensor_data
  WHERE `uuid1` IS NOT NULL AND Datetime >= [TIME_FILTER]
)
UNION ALL
(
  SELECT Datetime AS timestamp, 'uuid2' AS uuid, `uuid2` AS value
  FROM sensor_data
  WHERE `uuid2` IS NOT NULL AND Datetime >= [TIME_FILTER]
)
ORDER BY Datetime DESC
LIMIT 1000;

Time Filter Rules:
- If "today" in query: Datetime >= CURDATE() AND Datetime < CURDATE() + INTERVAL 1 DAY
- If "yesterday" in query: Datetime >= CURDATE() - INTERVAL 1 DAY AND Datetime < CURDATE()
- If "last N hours" in query: Datetime >= NOW() - INTERVAL N HOUR
- If "last N days" in query: Datetime >= NOW() - INTERVAL N DAY
- Otherwise (default): Datetime >= NOW() - INTERVAL 1 DAY

Return ONLY the SQL query, no markdown, no explanations.
"""
                sql_query = await llm_manager.generate(prompt)
                sql_query = sql_query.replace("```sql", "").replace("```", "").strip()
                
                logger.info(f"\n📝 Generated SQL for UUIDs ({storage_key}):")
                logger.info(f"   {sql_query}")
                
                logger.info(f"\n⚙️  Executing SQL query...")
                results = await self._execute_query(sql_query)
                
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
                "results": standardized_data, # Standardized JSON for Analytics
                "formatted_response": formatted,
                "analytics_required": True
            }
        except Exception as e:
            logger.error(f"Fetch data for UUIDs failed: {e}")
            return {"success": False, "error": str(e)}

    async def _get_schema(self) -> str:
        """Get database schema information with intelligent column detection"""
        try:
            conn = await aiomysql.connect(**self.db_config)
            async with conn.cursor() as cursor:
                # Get table names
                await cursor.execute("SHOW TABLES")
                tables = await cursor.fetchall()
                
                schema_info = "Database Schema:\n\n"
                timestamp_col_detected = None
                
                for (table_name,) in tables:
                    schema_info += f"Table: {table_name}\n"
                    
                    # Get column info
                    await cursor.execute(f"DESCRIBE {table_name}")
                    columns = await cursor.fetchall()
                    
                    for col in columns:
                        col_name = col[0]
                        col_type = col[1]
                        schema_info += f"  - {col_name} ({col_type})\n"
                        
                        # Detect timestamp/datetime column
                        if not timestamp_col_detected:
                            col_lower = col_name.lower()
                            type_lower = col_type.decode('utf-8').lower() if isinstance(col_type, bytes) else str(col_type).lower()
                            if 'datetime' in col_lower or 'timestamp' in col_lower or 'date' in type_lower or 'time' in type_lower:
                                timestamp_col_detected = col_name
                    
                    schema_info += "\n"
                
                # Add critical note about timestamp column
                if timestamp_col_detected:
                    schema_info += f"\n⚠️  CRITICAL: The timestamp column is named '{timestamp_col_detected}' (case-sensitive).\n"
                    schema_info += f"    Always use '{timestamp_col_detected}' in SELECT, WHERE, and ORDER BY clauses.\n"
                    schema_info += f"    You can alias it as 'timestamp' in SELECT (e.g., '{timestamp_col_detected} AS timestamp').\n"
                
                conn.close()
                return schema_info
                
        except Exception as e:
            logger.error(f"Schema retrieval error: {e}")
            return "Schema unavailable"
    
    async def _generate_sql(self, user_query: str, schema: str) -> str:
        """Generate SQL query using LLM"""
        
        # Parse time references
        time_context = self._parse_time_references(user_query)
        
        sql_prompt = f"""You are a SQL expert for building time-series data.

{schema}

IMPORTANT: The 'sensor_data' table uses a WIDE format where each sensor UUID is a COLUMN name.
The table has a 'Datetime' column (capital D) and many columns named after sensor UUIDs (e.g., '5dd84aa6...').

Time Context:
{time_context}

User Query: {user_query}

CRITICAL RULES:
1. The timestamp column is 'Datetime' (capital D) - use it in ALL clauses (SELECT, WHERE, ORDER BY).
2. Select 'Datetime AS timestamp', the UUID column as 'value', and the UUID as string literal for 'uuid'.
3. Filter by time using 'Datetime' column (NOT 'timestamp').
4. NO AGGREGATION (no AVG, SUM, etc.) - fetch raw rows only.
5. Limit to 1000 rows max.
6. Order by 'Datetime DESC'.

Time Filter Examples:
- Today: WHERE Datetime >= CURDATE() AND Datetime < CURDATE() + INTERVAL 1 DAY
- Yesterday: WHERE Datetime >= CURDATE() - INTERVAL 1 DAY AND Datetime < CURDATE()
- Last N hours: WHERE Datetime >= NOW() - INTERVAL N HOUR
- Default (24h): WHERE Datetime >= NOW() - INTERVAL 1 DAY

Template:
SELECT 
  Datetime AS timestamp,
  `uuid_column` AS value,
  'uuid_value' AS uuid
FROM sensor_data 
WHERE Datetime >= [TIME_CONDITION]
  AND `uuid_column` IS NOT NULL
ORDER BY Datetime DESC 
LIMIT 1000;

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
            now = datetime.now(ZoneInfo("Europe/London"))
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
            match = re.search(r'(\d+)\s*hours?', query_lower)
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
    
    def validate_sql(self, sql: str) -> bool:
        """
        Validate SQL query for security and safety.
        Returns True if safe, raises ValueError if unsafe.
        """
        sql_upper = sql.upper().strip()
        
        # 1. Ensure it's a SELECT query
        if not sql_upper.startswith("SELECT") and not sql_upper.startswith("WITH") and not sql_upper.startswith("("):
            raise ValueError("Only SELECT queries are allowed.")
            
        # 2. Check for forbidden keywords (DML/DDL)
        # Note: We check for keyword + space to avoid matching substrings like "UPDATE_TIME"
        forbidden_keywords = [
            "DROP ", "DELETE ", "INSERT ", "UPDATE ", "ALTER ", 
            "TRUNCATE ", "GRANT ", "REVOKE ", "CREATE ", "REPLACE "
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

    async def _execute_query(self, sql: str) -> List[Dict[str, Any]]:
        """Execute SQL query and return results"""
        try:
            # Validate SQL before execution
            self.validate_sql(sql)
            
            conn = await aiomysql.connect(**self.db_config)
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute(sql)
                results = await cursor.fetchall()
                
                conn.close()
                
                # Convert Decimal to float and datetime to string for JSON serialization
                from decimal import Decimal
                for row in results:
                    for key, value in row.items():
                        if isinstance(value, Decimal):
                            row[key] = float(value)
                        elif isinstance(value, datetime):
                            row[key] = value.isoformat()
                
                logger.info(f"SQL query returned {len(results)} rows")
                return results
                
        except Exception as e:
            logger.error(f"SQL execution error: {e}")
            raise Exception(f"Failed to execute SQL query: {str(e)}")
    
    async def _format_results(
        self,
        results: List[Dict[str, Any]],
        user_query: str,
        sql_query: str
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
            summary = await llm_manager.generate(summary_prompt)
            return summary.strip()
        except:
            return result_text  # Fallback to raw results
