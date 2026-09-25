"""
SQL Agent - Time-series data queries for Building 1
"""

import sys

sys.path.append("/app")

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from zoneinfo import ZoneInfo

from orchestrator.llm_manager import TaskType, llm_manager
from orchestrator.services.adapters.registry import adapter_registry
from orchestrator.services.prompt_builder import get_prompt_builder
from orchestrator.services.requested_interval import calendar_day_bounds
from shared.config import settings
from shared.models import ConversationState
from shared.utils import get_logger


def _day_bounds(day_word: str, now: Optional[datetime] = None) -> Optional[Tuple[str, str]]:
    """Local bounds for a named calendar day, from the ONE resolver (V12-08).

    This agent must not own a second answer to "when is yesterday". It delegates to the
    resolver that produced the interval upstream, so the prompt hint and the compiled
    window cannot disagree about what a day IS.

    Guarded because a time HINT failing must never sink a turn that would otherwise answer.
    """
    try:
        return calendar_day_bounds(day_word, settings.BUILDING_TIMEZONE, now=now)
    except Exception:  # pragma: no cover - a hint is never worth an exception
        return None


def _parse_window_start(value: Optional[str]) -> Optional[datetime]:
    """The start of the requested window as a datetime, or None when it is not a date.

    None means "no bounded window", and the caller must then skip the coverage check
    entirely: with no start there is nothing a store can be shown to predate, so dropping a
    point would be a guess rather than a proof.
    """
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[: len(fmt) + 2].strip(), fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


logger = get_logger(__name__)

#: How many sensors this lane will read for one question before declining as too broad.
#:
#: A budget, not a property of any building: it bounds what can be fetched, summarised and
#: narrated inside a single request. Sized to clear an ordinary floor-and-modality question
#: comfortably while stopping a whole-building sweep, and deliberately larger than the
#: deliberation lane's space budget because this counts SENSORS, several of which sit in
#: each space.
MAX_FETCH_UUIDS = 600

#: WB-04 — the real limit, in ROWS. 200 sensors × 1,000 rows was the old implicit budget; a
#: "right now" question needs the last readings only, so a building-wide one (288 temperature
#: sensors × 60 rows) is cheaper than a floor-wide week. Declines when sensors × rows-per-sensor
#: exceeds this, and names the narrowing as before.
MAX_FETCH_ROWS = 200_000
NOW_ROWS_PER_UUID = 60
DEFAULT_ROWS_PER_UUID = 1000

#: The window a question with no stated bounds is read over.
#:
#: Named once because it is stated twice: `_build_uuid_union_query` puts it in the WHERE
#: clause, and the substitution disclosure has to tell the user which period came back
#: empty. Two copies of this number would let the answer name a window the query did not
#: use — the same drift that let a truncated set be reported as a count (BUG-479).
DEFAULT_LOOKBACK_DAYS = 30

#: Rows per sensor read by the empty-window fallback: a recent sample, never a whole history.
FALLBACK_ROWS_PER_UUID = 200

#: The lower bound the empty-window fallback hands the store's own query builder (BUG-660).
#:
#: Every builder applies its OWN default lookback when it is given no bounds at all, so asking
#: again with (None, None) re-asks the question that just came back empty. A floor before any
#: store's first reading lifts that lookback without removing the bound, and keeps the store's
#: newest-first, per-sensor limit doing the work. It is a sentinel, not a date any building owns:
#: the day after the epoch, so it stays inside a TIMESTAMP column's range.
_FALLBACK_FLOOR = "1970-01-02 00:00:00"

_NOW_RE = re.compile(
    r"\b(?:right now|now|currently|current|at the moment|latest|live|at present)\b", re.IGNORECASE
)
_PERIOD_RE = re.compile(
    r"\b(?:yesterday|today|last|past|this (?:week|month|morning|afternoon)|since|between|"
    r"over the|trend|history|average over|daily|weekly|monthly|overnight|weekend)\b",
    re.IGNORECASE,
)


def rows_per_uuid_for(query: str) -> int:
    """How many recent rows per sensor a question needs: few for 'now', the default otherwise."""
    q = query or ""
    return (
        NOW_ROWS_PER_UUID
        if _NOW_RE.search(q) and not _PERIOD_RE.search(q)
        else DEFAULT_ROWS_PER_UUID
    )


def over_fetch_budget(n_uuids: int, rows_per_uuid: int) -> bool:
    """True when reading this many sensors row by row would break the lane's budget.

    One definition, used by the refusal and by the aggregate lane that answers in the store
    instead (2D-10), so the two can never disagree about which questions are "too broad".
    """
    return n_uuids > MAX_FETCH_UUIDS or n_uuids * rows_per_uuid > MAX_FETCH_ROWS


#: Bare period words that neither regex above carries. Kept as a set rather than folded into
#: `_PERIOD_RE` because these are substring tests on purpose ("hour" inside "hourly").
_PERIOD_WORDS = frozenset(
    {
        "hour",
        "day",
        "week",
        "month",
        "year",
        "before",
        "after",
        "from",
        "until",
    }
)


def _widen(current: str, candidate: str, pick) -> str:
    """Extend a span bound with another, ignoring bounds that could not be read."""
    known = [s for s in (current, candidate) if s]
    return pick(known) if known else ""


def names_a_period(query: str) -> bool:
    """Does this question name a period — past OR present — that an answer must honour?

    THE LIST IS THE WEAK PART, AND IT IS NOT THE PROTECTION.

    This guard used to be a bare keyword list of fourteen past-tense words. It had no
    present tense in it at all, so "what is the CO2 in this room right now" was treated as a
    question that named no period, and the lane was free to answer it from whatever rows it
    could find — on this building, potentially months behind the question, with nothing in
    the answer saying so.

    Adding the present tense closes that hole and creates the next one, because every list
    like this decays. So the list is no longer load-bearing: a substitution is DISCLOSED
    whether or not this returns True (see the marker written in `fetch_data_for_uuids`).
    A word this misses now costs a visible sentence, not a silent lie.

    Reuses `_NOW_RE` and `_PERIOD_RE`, which already carry this vocabulary for the row
    budget, so the two readings of a question cannot disagree about whether it said "now".
    """
    q = (query or "").lower()
    if _NOW_RE.search(q) or _PERIOD_RE.search(q):
        return True
    return any(word in q for word in _PERIOD_WORDS)


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

            # Step 1: Get database schema, naming the sensors this turn is about.
            #
            # This is the FALLBACK path — it reaches the LLM without a resolved UUID
            # group — but the turn usually still knows which sensors it resolved, on the
            # bus. Naming them keeps the wide table's schema proportional to the QUESTION;
            # without them `as_prompt_text` falls back to a sample of the shape, which is
            # still bounded. Listing all 704 columns is what produced an empty completion
            # from a 45,573-character prompt and a data-free report (BUG-474).
            schema = await self._get_schema(self._turn_uuids(state))

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
                    "This may be because the sensor type you're asking about isn't monitored "
                    "in this building, or its readings aren't loaded yet. "
                    'Ask "what sensors are available?" to see the sensor types this building '
                    "actually monitors."
                ),
                "analytics_required": False,
            }

    @staticmethod
    def _row_time(row: Dict[str, Any]):
        """The timestamp on a row, whatever the adapter called the column."""
        from datetime import datetime as _dt

        ts = row.get("timestamp") or row.get("Datetime") or row.get("datetime")
        if isinstance(ts, _dt):
            return ts
        if isinstance(ts, str):
            try:
                return _dt.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None

    @classmethod
    def _coarsen(cls, rows: List[Dict[str, Any]], max_resolution_s: float) -> List[Dict[str, Any]]:
        """Average rows into buckets no finer than the policy allows (BUG-356).

        The PDP has always been able to say "this role may not have data finer than N
        seconds", and the SQL lane has always served whatever the query returned. So a
        RESTRICT verdict with a resolution clamp was recorded in applied_policies and
        then ignored: measured live, the PDP said "resolution clamped to 3600s" and the
        answer went out as a ten-row table at five-second spacing.

        Averaging rather than sampling, because the point is that the fine detail must
        not survive: taking every Nth row would still hand back individual instants.

        A row whose timestamp cannot be read is DROPPED. Keeping it would let a reading
        of unknown time through a rule that exists to control timing.
        """
        buckets: Dict[Any, List[Dict[str, Any]]] = {}
        for row in rows:
            when = cls._row_time(row)
            if when is None:
                continue
            key = (
                str(row.get("uuid") or row.get("UUID") or ""),
                int(when.timestamp() // max_resolution_s),
            )
            buckets.setdefault(key, []).append(row)

        out: List[Dict[str, Any]] = []
        for (_uuid, slot), group in sorted(buckets.items(), key=lambda kv: kv[0][1]):
            merged = dict(group[0])
            for col in group[0]:
                values = []
                for r in group:
                    v = r.get(col)
                    if isinstance(v, bool):
                        continue
                    if isinstance(v, (int, float)):
                        values.append(float(v))
                if values:
                    merged[col] = round(sum(values) / len(values), 4)
            from datetime import datetime as _dt
            from datetime import timezone as _tz

            merged_ts = _dt.fromtimestamp(slot * max_resolution_s, tz=_tz.utc)
            for col in ("timestamp", "Datetime", "datetime"):
                if col in merged:
                    merged[col] = merged_ts.strftime("%Y-%m-%d %H:%M:%S")
                    break
            out.append(merged)
        return out

    @classmethod
    def _aggregate_across_sensors(cls, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Collapse per-sensor rows into ONE series — the aggregation floor, enforced.

        BUG-356(b). A policy may say a role gets "building-wide aggregates only,
        k-protected" (readonly's cross-space policy sets minSensors 14, minSpaces 7). The
        floor was only ever checked as "does this FETCH cover enough sensors" -- 288 >= 14,
        so it passed -- and never as "is the ANSWER aggregated". The lane then listed the
        rooms one by one, which is the thing the floor exists to prevent: a list of
        per-room values is a map of where people are.

        Applied only to an enumeration across spaces. A question about ONE room is not a
        map of anything, and aggregating it would refuse an ordinary question in the name
        of a rule that was never about it.
        """
        buckets: Dict[Any, List[Dict[str, Any]]] = {}
        for row in rows:
            when = cls._row_time(row)
            buckets.setdefault(when.isoformat() if when else "", []).append(row)

        out: List[Dict[str, Any]] = []
        for _when, group in sorted(buckets.items()):
            merged: Dict[str, Any] = {}
            for col in group[0]:
                values = [
                    float(r[col])
                    for r in group
                    if isinstance(r.get(col), (int, float)) and not isinstance(r.get(col), bool)
                ]
                if values:
                    merged[col] = round(sum(values) / len(values), 4)
                elif col in ("timestamp", "Datetime", "datetime"):
                    merged[col] = group[0][col]
            # The identity of the contributing sensors is what must NOT survive.
            merged["sensors_combined"] = len(group)
            out.append(merged)
        return out

    async def _try_aggregate_lane(
        self,
        uuids: List[str],
        user_query: str,
        storage_map: Optional[Dict[str, str]],
        start_date: Optional[str],
        end_date: Optional[str],
        sensor_metadata: Optional[Dict[str, Dict[str, str]]],
        max_resolution_s: Optional[float] = None,
        aggregate_across_sensors: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """The store's own aggregates for a per-floor / whole-building question, else None.

        Never costs a turn: any failure is logged and the lane carries on as it did. A store the
        registry has no adapter for is not borrowed from the default one, which reads a narrow
        store's uuid as a column name. The policy decision's two limits ride along: a reader held
        to a coarser resolution, or to building-wide aggregates, is not handed finer detail.
        """
        try:
            from orchestrator.services import aggregate_lane
            from orchestrator.services.deliberation.live import sparql_exec

            _lane_kwargs = dict(
                uuids=list(uuids),
                storage_map=storage_map,
                metadata=sensor_metadata,
                budget_hit=over_fetch_budget(len(uuids), rows_per_uuid_for(user_query)),
                adapter_for=lambda uri: adapter_registry._adapters.get(
                    adapter_registry._resolve_storage_key(uri or "")
                ),
                store_key=adapter_registry._resolve_storage_key,
                sparql_exec=sparql_exec,
                resolution_clamp_s=max_resolution_s,
                aggregate_only=aggregate_across_sensors,
            )
            # W1-04: a question naming TWO periods gets both fetched. Measured 2026-09-23,
            # "compare the average CO2 this week against last week" fetched a 14-hour window and
            # said it could not compare, and "yesterday versus the same day last week" declined
            # outright -- in both cases because only one window was ever resolved. This runs the
            # same lane a second time over the baseline period and states both figures and the
            # difference; it returns None for every one-period question, which is nearly all of
            # them, leaving the call below exactly as it was.
            from orchestrator.services import comparison_lane

            answer = await comparison_lane.try_compare(
                question=user_query,
                try_answer=aggregate_lane.try_answer,
                start_date=start_date,
                end_date=end_date,
                tz_name=settings.BUILDING_TIMEZONE,
                **_lane_kwargs,
            )
            if answer is None:
                answer = await aggregate_lane.try_answer(
                    question=user_query,
                    start_date=start_date,
                    end_date=end_date,
                    tz_name=settings.BUILDING_TIMEZONE,
                    **_lane_kwargs,
                )
            # SAY WHICH WORDS WERE NOT HONOURED (2026-09-19). "Which COMMISSIONED CO2-monitored
            # zones show sustained elevated CO2 during an APPROVED occupied period?" is computable
            # as an exceedance, and no series records commissioning or approval. The figures are
            # given, and one sentence says what the records could not narrow by.
            if answer and answer.get("formatted_response"):
                from orchestrator.services.unrecorded_qualifiers import caveat

                note = caveat(user_query, "every zone with readings in the window")
                if note and note not in answer["formatted_response"]:
                    answer["formatted_response"] += f"\n\n{note}"
            return answer
        except Exception as exc:  # the aggregate lane is an addition; it must not break the read
            logger.warning(f"[sql] aggregate lane skipped: {exc}", exc_info=True)
            return None

    async def fetch_data_for_uuids(
        self,
        uuids: List[str],
        user_query: str,
        storage_map: Optional[Dict[str, str]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        sensor_metadata: Optional[Dict[str, Dict[str, str]]] = None,
        max_resolution_s: Optional[float] = None,
        aggregate_across_sensors: bool = False,
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
                    "formatted_response": (
                        "The sensor readings are unavailable right now. I can still answer "
                        "questions about the building's spaces, equipment and sensors."
                    ),
                    "analytics_required": False,
                }

            logger.info("=" * 80)
            logger.info("SQL AGENT: Fetching Data for UUIDs")
            logger.info("=" * 80)
            logger.info(f"User Query: {user_query}")
            logger.info(f"UUIDs to fetch: {len(uuids)}")

            # A whole-building or per-floor aggregate is answered by the store itself, BEFORE the
            # breadth refusal below (2D-10, BUG-808/814). Returns None to leave everything as it was.
            _agg = await self._try_aggregate_lane(
                uuids, user_query, storage_map, start_date, end_date, sensor_metadata,
                max_resolution_s, aggregate_across_sensors,
            )
            if _agg is not None:
                return _agg

            # Too many sensors to read inside one request (V7-T24).
            #
            # Measured 2026-08-31: "show me live setpoints versus measured temperature for
            # all zones on floor 5" reached this lane with 288 uuids. Before the budget it
            # timed out at 120 s; capping the deliberation lane alone simply moved the
            # question here, where it fetched all 288 and then narrated ONE sensor — on a
            # different floor from the one asked about. Faster, and wrong, which is worse
            # than slow.
            #
            # Declining names the narrowing. Truncating would answer over an unnamed subset
            # of the building, which is the failure this project guards hardest against.
            _rows_per_uuid = rows_per_uuid_for(user_query)
            if over_fetch_budget(len(uuids), _rows_per_uuid):
                # ONE PLAIN SENTENCE, IN THE READER'S OWN WORDS (wave 2).
                #
                # This used to describe the mechanism: "more than I can read row by row and
                # summarise in one request without either timing out or quietly answering from a
                # fraction of them", two bullets, and a paragraph justifying itself. Measured in
                # the stakeholder reads, it reached people who had asked a KNOWLEDGE question and
                # read, to everyone, as a wall of jargon about the system's internals.
                #
                # The budget is unchanged and so is the refusal. What the reader gets is what was
                # asked, and the two cheapest questions that do have an answer, built from their
                # own quantity and period so they can be asked as they stand.
                #
                # Imported here, not at the top: this module is reached through the package's
                # `__init__`, and a module-level import of another service re-enters a
                # half-initialised `orchestrator` package (the whole test suite fails to collect
                # with `KeyError: 'orchestrator'`, which names nothing useful).
                from orchestrator.services.too_broad_reply import too_broad_reply

                msg = too_broad_reply(
                    user_query,
                    len(uuids),
                    [
                        str((m or {}).get("label") or "")
                        for m in (sensor_metadata or {}).values()
                    ],
                )
                logger.info(f"[sql] declining as too broad: {len(uuids)} > {MAX_FETCH_UUIDS}")
                return {
                    "success": True,
                    "query": "Breadth Budget (No Fetch)",
                    "results": {"data": []},
                    "formatted_response": msg,
                    "analytics_required": False,
                    "too_broad": True,
                    "uuids_requested": len(uuids),
                }
            for i, uuid in enumerate(uuids, 1):
                storage = storage_map.get(uuid, "N/A") if storage_map else "N/A"
                logger.info(f"   {i}. {uuid} (Storage: {storage})")

            # VALIDATION: Validate UUIDs against DB columns (via adapter registry)
            # Use the first non-null storage URI from the storage_map to route to correct DB
            primary_storage_uri = None
            if storage_map:
                primary_storage_uri = next((v for v in storage_map.values() if v), None)
            # BUG-234: pass the WHOLE map. Validating every uuid against one adapter --
            # whichever store happened to be first -- reported sensors in every other store
            # as absent from the database while they held tens of thousands of rows.
            valid_uuids = await adapter_registry.get_valid_uuids(
                uuids, primary_storage_uri, storage_map=storage_map
            )
            missing_uuids = set(uuids) - set(valid_uuids)

            if missing_uuids:
                logger.warning(
                    f"⚠️  {len(missing_uuids)} UUIDs found in Ontology are MISSING in SQL Database."
                )
                # logger.debug(f"Missing: {missing_uuids}")

            if not valid_uuids:
                # BUG-234: say what was actually checked. "None exist in the time-series
                # database" is a claim about the estate's configuration; what was checked is
                # whether these ids appear in the stores they are registered to. Telling
                # users their sensors are not connected when they are sends them to fix the
                # wrong thing.
                _stores = sorted(
                    {
                        adapter_registry._resolve_storage_key(str(v))
                        for v in (storage_map or {}).values()
                        if v
                    }
                )
                _where = f" ({', '.join(_stores)})" if _stores else ""
                # Every reader sees this, and this function does not know who is reading, so
                # it is worded for the least technical of them (2026-09-17 user decision):
                # no "ontology", no "registered", no store keys, nothing to go and load. The
                # store names stay in the log, where the person who can act on them looks.
                msg = (
                    f"I found {len(uuids)} sensor(s) for this in the building's records, but "
                    "no readings from any of them are available to me. The sensors are on "
                    "record, so this is missing readings rather than missing sensors."
                )
                logger.warning(f"❌ {msg} stores checked{_where or ': none resolved'}")
                return {
                    "success": True,
                    "query": "Metadata Check (No Columns)",
                    "results": {"data": []},
                    "formatted_response": msg,
                    "analytics_required": False,
                }

            # Continue with valid UUIDs only
            uuids = valid_uuids

            # Set aside points whose store PROVABLY predates the window (BUG-378).
            #
            # Room 5.04 has two temperature points: the real sensor in the wide store, with
            # 1,045 readings on the date asked about, and a synthetic `_sat_` overlay point on
            # a narrow table frozen five days earlier. Reading the second and reporting "No
            # data found" is not a data gap, it is a selection defect — and it is broad: 665
            # of the 728 points on the eight frozen stores are that same overlay shadowing a
            # live sensor.
            #
            # Conservative by construction. Only a store whose newest reading is proven to
            # predate the window is dropped; UNKNOWN is kept, so a probe failure can never
            # silence a sensor. And if this would drop EVERYTHING, nothing is dropped — the
            # frozen reading is then the only evidence there is, and the freshness gate is
            # what says it is old. Discarding it here would replace a stale answer with none.
            skipped_reasons: Dict[str, str] = {}
            if len(uuids) > 1 and start_date:
                try:
                    uuids, skipped_reasons = await self._drop_uncoverable_uuids(
                        uuids, storage_map, start_date
                    )
                except Exception as exc:  # never let a freshness probe break a fetch
                    logger.warning(f"[sql] store-coverage check skipped: {exc}")
                    skipped_reasons = {}

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

            # A SENSOR CAP THAT IS STATED, SIZED FOR A FLOOR, AND DETERMINISTIC (BUG-534).
            #
            # This was 30, applied as `grouped_uuids[key][:30]`, with one log line and nothing
            # in the answer. Measured 2026-09-15 on "Compare the average CO2 on floor 1 versus
            # floor 3": 61 sensors in one store, and the slice kept 5 of floor 1's 13 and 25 of
            # floor 3's 48 — so a floor-1 average over 5 of 13 sensors was stated as the floor
            # average. Which ones survived was whatever order SPARQL returned.
            #
            # 30 was sized for an LLM prompt. It no longer needs to be: `_format_results` shows
            # the model at most 10 rows, the statistics are computed in code, and the per-uuid
            # row limit keeps each sensor's fetch bounded. 120 matches the deliberation lane's
            # MAX_FETCH_CANDIDATES — above any floor here, below the whole building.
            #
            # When it still binds, the kept set is SORTED (stable across runs, not dependent on
            # result order) and the omission is recorded and said.
            # WB-04: raised with the row budget above — the building, not a floor, is the unit
            # a "right now" question may cover. Still sorted, recorded and stated when it binds.
            _UUID_CAP = 600
            points_capped: Dict[str, Tuple[int, int]] = {}
            for key in grouped_uuids:
                total = len(grouped_uuids[key])
                if total > _UUID_CAP:
                    grouped_uuids[key] = sorted(grouped_uuids[key])[:_UUID_CAP]
                    points_capped[key] = (_UUID_CAP, total)
                    logger.warning(
                        "[sql] store %s: %d sensors match, reading %d — the answer will say so",
                        key,
                        total,
                        _UUID_CAP,
                    )

            all_data = []
            #: Rows per storage group. Named rather than repeated inline so the cap and the
            #: check that detects hitting it cannot drift apart — that drift is how a
            #: truncated set came to be reported as a count (BUG-479).
            _row_limit = _rows_per_uuid
            # BUG-591: a BOUNDED interval ("yesterday") is read whole where the budget allows.
            # The fixed 1,000 cut a one-room day report to its newest ~8 h (disclosed as "a
            # slice", and once turned into a recommendation to "increase the row limit",
            # BUG-506). 120 rows/h covers a 30-second cadence; the row budget still bounds it.
            if start_date and end_date and _row_limit >= DEFAULT_ROWS_PER_UUID:
                try:
                    from orchestrator.services.requested_interval import interval_hours

                    _hours = interval_hours(start_date, end_date) or 0.0
                    if _hours > 0:
                        _row_limit = int(
                            min(
                                max(_row_limit, _hours * 120),
                                MAX_FETCH_ROWS // max(1, len(uuids)),
                            )
                        )
                        _row_limit = max(_row_limit, _rows_per_uuid)
                except Exception as _ri_err:  # the default read still answers
                    logger.debug(f"[sql] interval row plan skipped: {_ri_err}")
            #: Did any group come back exactly full? Then `all_data` is a TRUNCATED sample
            #: and its length is not a count of what exists.
            rows_capped = False
            #: Set when the requested window held nothing and the lane answered from the
            #: most recent rows on record instead. None means the answer covers the period
            #: that was asked for — the ONLY state in which saying nothing is honest.
            window_substituted: Optional[Dict[str, Any]] = None

            # V6-T40: a recurring-window question ("overnight", "at the weekend", "around
            # lunchtime") filters by HOUR, not by date range. Detected once, applied twice:
            # as a predicate inside the deterministic SQL (so LIMIT cannot be exhausted by
            # daytime rows) and again in Python over whatever came back (which also covers
            # the LLM-generated and fallback paths).
            _hour_mask = None
            try:
                from orchestrator.services.evidence.time_windows import detect_mask

                _hour_mask = detect_mask(user_query)
                if _hour_mask is not None:
                    logger.info(f"[sql] recurring window detected: {_hour_mask.label}")
            except Exception as _tw_err:
                logger.debug(f"[sql] time-window detection skipped: {_tw_err}")

            # Process each storage group (currently only supporting MySQL/default)
            for storage_key, group_uuids in grouped_uuids.items():
                if not group_uuids:
                    continue

                logger.info(
                    f"Fetching data for {len(group_uuids)} UUIDs from storage: {storage_key}"
                )

                # Phase 2.5: Pick the right adapter for this storage location
                adapter = adapter_registry.get(storage_key)
                schema_text = adapter_registry.get_schema_text(
                    storage_key, keep_columns=set(group_uuids)
                )
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
                        limit=_row_limit,
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
                    limit=_row_limit,
                    hour_predicate=(_hour_mask.sql_predicate(ts_col) if _hour_mask else ""),
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

                #: The per-read limit these rows were fetched under; the fallback reads fewer.
                _group_limit = _row_limit

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
                    # THE SUBSTITUTION THIS GUARDS IS THE DANGEROUS KIND (BUG-658).
                    #
                    # Below, the lane drops every date bound and answers from the most
                    # recent rows on record. That is defensible ONLY when the question named
                    # no period and the answer says which period it did use. Neither held:
                    # the guard was a past-tense keyword list with no present tense in it, so
                    # "…right now" walked through it, and nothing anywhere recorded that a
                    # substitution had occurred — two log lines and no marker, so no
                    # downstream gate, disclosure or evidence record could know.
                    has_explicit_time = names_a_period(user_query)
                    if not has_explicit_time:
                        logger.warning(
                            "⚠️  0 rows with default time window. Retrying with latest available data..."
                        )
                        # BUG-660: through THIS group's adapter and its own query builder. The
                        # fallback used to be hand-written wide-table SQL run on the DEFAULT
                        # adapter, so a narrow-table point was read as a column of the wrong
                        # store, and an adapter error escaped the lane as a failed turn.
                        _fallback_limit = FALLBACK_ROWS_PER_UUID
                        results = await self._latest_rows_from_store(
                            adapter, storage_key, group_uuids, ts_col, _fallback_limit
                        )
                        if results:
                            _group_limit = _fallback_limit
                            # RECORDED, not merely logged. The span is the honest part:
                            # "we substituted" is a process note, "these readings end on
                            # <date>" is a fact the reader can act on. Recorded for the
                            # FIRST group that substitutes — one disclosure per answer,
                            # and the span widens below as further groups substitute.
                            _earliest, _latest = self._row_span(results)
                            if window_substituted is None:
                                window_substituted = {
                                    "substituted": True,
                                    "requested_start": str(start_date or ""),
                                    "requested_end": str(end_date or ""),
                                    "requested_label": self._requested_window_label(
                                        start_date, end_date
                                    ),
                                    "actual_earliest": _earliest,
                                    "actual_latest": _latest,
                                    "rows": len(results),
                                    "stores": [storage_key],
                                }
                            else:
                                window_substituted["rows"] += len(results)
                                window_substituted["stores"].append(storage_key)
                                window_substituted["actual_earliest"] = _widen(
                                    window_substituted["actual_earliest"], _earliest, min
                                )
                                window_substituted["actual_latest"] = _widen(
                                    window_substituted["actual_latest"], _latest, max
                                )
                            logger.warning(
                                "[sql] WINDOW SUBSTITUTED for store %s: the requested "
                                "window held no rows, answering from %s rows spanning "
                                "%s..%s — the answer will say so",
                                storage_key,
                                len(results),
                                _earliest or "unknown",
                                _latest or "unknown",
                            )

                if results:
                    logger.info(f"✅ Query returned {len(results)} rows")
                    if results:
                        logger.info(f"📊 Sample row: {results[0]}")
                    # A QUERY THAT RETURNED EXACTLY ITS LIMIT WAS CUT SHORT.
                    #
                    # Every timeseries query carries LIMIT 1000. Hitting it is not an
                    # error and nothing downstream could tell: a report said "Room 5.01
                    # recorded 1,000 CO2 sensor readings yesterday" when 2,770 were
                    # recorded and 1,000 was the cap (BUG-479). The statistics over those
                    # 1,000 rows were right; the sentence was a false claim about the
                    # building. "A cap on an exhaustive query does not fail, it
                    # under-reports" — and in prose it stops looking like a cap at all.
                    if len(results) >= _group_limit:
                        rows_capped = True
                        logger.info(
                            "[sql] group %s returned exactly its %s-row limit — the set is "
                            "TRUNCATED and its size is not a count of what exists",
                            storage_key,
                            _group_limit,
                        )
                    all_data.extend(results)
                else:
                    logger.warning(f"⚠️  No results returned from query")

            # V6-T40 second layer: enforce the mask over whatever the queries returned.
            # A row whose timestamp cannot be parsed is dropped UNDER A MASK, not kept: a
            # reading whose hour is unknowable cannot be claimed to lie inside the window.
            if _hour_mask is not None and all_data:
                from datetime import datetime as _dt

                _before_mask = len(all_data)
                _kept = []
                for _row in all_data:
                    _ts = _row.get("timestamp") or _row.get("Datetime") or _row.get("datetime")
                    _parsed = None
                    if isinstance(_ts, _dt):
                        _parsed = _ts
                    elif isinstance(_ts, str):
                        try:
                            _parsed = _dt.fromisoformat(_ts.replace("Z", "+00:00"))
                        except ValueError:
                            _parsed = None
                    if _parsed is not None and _hour_mask.covers(_parsed):
                        _kept.append(_row)
                all_data = _kept
                logger.info(
                    f"[sql] window '{_hour_mask.label}': {len(all_data)} of {_before_mask} "
                    "rows inside it"
                )

            # PROTECT: the policy decision point may cap how fine this role's data may
            # be. Applied HERE, on the rows, because a clamp that only reaches the log
            # is not enforcement -- the leak this fixes was a correct RESTRICT verdict
            # sitting beside a five-second table in the same response.
            if max_resolution_s and all_data:
                _before_res = len(all_data)
                all_data = self._coarsen(all_data, float(max_resolution_s))
                logger.info(
                    f"[sql] policy resolution clamp {max_resolution_s:g}s: "
                    f"{_before_res} rows -> {len(all_data)}"
                )

            # The aggregation floor, applied to the ANSWER rather than merely checked
            # against the fetch. Runs after the time clamp so the combined series is
            # already at the resolution the policy allows.
            if aggregate_across_sensors and all_data:
                _before_agg = len(all_data)
                all_data = self._aggregate_across_sensors(all_data)
                logger.info(
                    f"[sql] policy aggregation floor: {_before_agg} per-sensor rows -> "
                    f"{len(all_data)} combined row(s)"
                )

            # Standardize output format for Analytics Agent
            # We want a flat list of records: [{"timestamp": "...", "uuid": "...", "value": ...}, ...]
            standardized_data = {"data": all_data}

            formatted = await self._format_results(
                all_data, user_query, "Multiple Queries", sensor_metadata
            )
            if _hour_mask is not None:
                # The basis is stated on the answer itself: which recurring window, and how
                # many readings actually fall inside it. Without this a night question
                # answered from three rows reads exactly like one answered from a thousand.
                formatted += (
                    f"\n\n_Window applied: {_hour_mask.label} — "
                    f"{len(all_data)} reading(s) inside it._"
                )

            # THE PERIOD THESE FIGURES ARE ACTUALLY FROM (BUG-658).
            #
            # Emitted HERE, deterministically, for the same reason as the resolution clamp
            # two blocks down: the narration is given rows, not provenance, and left to
            # itself it echoes the period the QUESTION named. An answer to "right now" that
            # was computed from readings months older reads exactly like one that was not.
            #
            # The WORDING lives in `disclosure_gate` and the MARKER on the bus below, so the
            # sentence a reader sees and the record a later gate reads cannot drift apart.
            if window_substituted:
                from orchestrator.services.disclosure_gate import substitution_note

                formatted += substitution_note(window_substituted)

            if aggregate_across_sensors:
                # Disclosed, like the resolution clamp: an answer that silently became a
                # building average while the question asked room by room would misrepresent
                # what it is showing.
                formatted = (
                    "_Combined across sensors — this building's access policy allows you "
                    "aggregates rather than per-room values for a question of this scope. "
                    "The figures below are averages over all matching sensors._\n\n"
                ) + formatted

            if max_resolution_s:
                # Said DETERMINISTICALLY, not left to the narration. Measured: with the
                # rows correctly coarsened from 102,000 to 7,156 hourly means, the model
                # still headed its answer "updated every 5 s" — echoing the words of the
                # question. An answer that names a cadence its data does not have is a
                # false claim about the data, and here it also hid that a policy applied.
                _res = float(max_resolution_s)
                _human = (
                    f"{_res / 3600:g}-hour"
                    if _res >= 3600
                    else (f"{_res / 60:g}-minute" if _res >= 60 else f"{_res:g}-second")
                )
                formatted = (
                    f"_Served at {_human} resolution — this building's access policy sets "
                    f"the finest detail available to you for data this recent. The figures "
                    f"below are averages over each interval, not instantaneous readings._\n\n"
                ) + formatted

            # Points set aside because their store predates the window are NAMED (BUG-378).
            # Dropping a point the question named and then answering from the rest changes
            # the question without saying so; naming it is what makes the omission checkable.
            if skipped_reasons:
                from orchestrator.services.store_coverage import describe_skipped

                _note = describe_skipped(skipped_reasons, sensor_metadata)
                if _note:
                    formatted = f"{formatted}\n\n_{_note}_"

            # The cap, said (BUG-534). A figure over part of a set is only honest if the part
            # is named with its size — "averaged over 120 of 214 sensors" is an answer; the
            # same number without it is a claim about all 214.
            if points_capped:
                kept = sum(k for k, _ in points_capped.values())
                total = sum(t for _, t in points_capped.values())
                formatted = (
                    f"{formatted}\n\n_These figures are computed over {kept} of the {total} "
                    f"matching sensors: a single question reads at most {_UUID_CAP} per data "
                    f"store. Narrowing it to a floor or a room reads all of them._"
                )

            return {
                "success": True,
                "query": "Multiple Queries (Storage Aware)",
                "results": standardized_data,  # Standardized JSON for Analytics
                "formatted_response": formatted,
                "analytics_required": True,
                # Which points were not read, and why — carried so the evidence record can
                # state the omission rather than leaving it only in the prose.
                "points_omitted": dict(skipped_reasons),
                # {store: (read, matched)} for any store where the sensor cap bound (BUG-534).
                "points_capped": {k: list(v) for k, v in points_capped.items()},
                # Was any group cut off at the row limit? Then len(data) is the SIZE OF A
                # SAMPLE, never a count of what the period holds. A report said "Room 5.01
                # recorded 1,000 CO2 sensor readings yesterday" against a true 2,770
                # (BUG-479); the statistics were right and the sentence was false. Whoever
                # states a count must be able to see that it is capped.
                "rows_capped": rows_capped,
                "row_limit": _row_limit,
                # The clamp that shaped these rows, "" when none did — so the evidence
                # record can state the resolution actually served rather than inferring
                # it from timestamps that now describe buckets.
                "resolution_clamp_s": float(max_resolution_s) if max_resolution_s else "",
                # V6-T40: which recurring window shaped these rows, "" when none did. The
                # evidence record reads it so requested_period can state the real basis.
                "window_mask": _hour_mask.label if _hour_mask is not None else "",
                # BUG-658: did this answer come from a period OTHER than the one requested?
                # None when it did not. Read by `disclosure_gate.window_substitution_in`,
                # which is the single place any downstream gate, dossier or evidence record
                # should ask — the previous answer to that question was two log lines, which
                # no gate can read and no record can cite.
                "window_substituted": window_substituted,
            }
        except Exception as e:
            logger.error(f"Fetch data for UUIDs failed: {e}")
            return {"success": False, "error": str(e)}

    async def _drop_uncoverable_uuids(
        self,
        uuids: List[str],
        storage_map: Optional[Dict[str, str]],
        start_date: str,
    ) -> Tuple[List[str], Dict[str, str]]:
        """Drop points whose store cannot hold anything in the window. See BUG-378.

        Returns (kept, {dropped_uuid: why}). The all-or-nothing guard is the important part:
        if every point would be dropped, none is. A stale reading is still evidence about the
        recent past, and the freshness gate exists to label it as such — throwing it away here
        would turn "this is five days old" into "there is nothing", which is a worse answer
        and a false one.
        """
        from orchestrator.services import store_coverage

        window_start = _parse_window_start(start_date)
        if window_start is None:
            return uuids, {}

        by_store: Dict[str, List[str]] = {}
        for uid in uuids:
            by_store.setdefault(store_coverage._store_key((storage_map or {}).get(uid)), []).append(
                uid
            )

        latest_by_store: Dict[str, Optional[datetime]] = {}
        latest_by_uuid: Dict[str, Optional[datetime]] = {}
        for store, store_uuids in sorted(by_store.items()):
            if not store:
                continue
            try:
                adapter = adapter_registry.get(store)
            except Exception:
                adapter = None
            if adapter is None:
                continue
            # PER-SENSOR freshness where the adapter can report it, because a store's
            # MAX(timestamp) is not a statement about any particular sensor in it. Measured:
            # noise_data holds 236 uuids and ONE has written in the last 24h; light_data 242
            # with one; occupancy_data 280 with six. A store-level check calls all three
            # current while 99% of their points are eight days dead. Across bldg1's narrow
            # tables only 19 of ~933 points are live.
            per_uuid = getattr(adapter, "latest_by_uuid", None)
            if per_uuid is not None:
                try:
                    latest_by_uuid.update(await per_uuid(store_uuids))
                    continue
                except Exception as exc:
                    logger.warning(f"[sql] per-uuid freshness failed for {store}: {exc}")
            # Wide tables keep the store-level check: a sensor is a COLUMN there and the
            # publisher writes whole rows, so the table's newest row does describe them all.
            latest_by_store[store] = await store_coverage.latest_observation(store, adapter)

        kept, dropped, reasons = store_coverage.partition_by_coverage(
            uuids, storage_map, latest_by_store, window_start, latest_by_uuid=latest_by_uuid
        )
        if not kept:
            return uuids, {}
        if dropped:
            logger.info(
                f"[sql] set aside {len(dropped)} point(s) whose store predates the window: "
                f"{sorted(reasons.values())[:2]}"
            )
        return kept, reasons

    async def _latest_rows_from_store(
        self,
        adapter: Any,
        storage_key: str,
        group_uuids: List[str],
        ts_col: str,
        limit: int,
    ) -> List[Dict[str, Any]]:
        """The most recent rows for one storage group, read through that group's adapter.

        The empty-window fallback (BUG-660). Built by the adapter's own
        `build_timeseries_query`, so the store decides its table and shape — the agent names
        neither (design contract 9). Bounded newest-first, `limit` rows per sensor.

        Never raises. No adapter, a builder that declines or throws, an unsuccessful result
        and an exception all come back as [] with a WARNING naming the store: a fallback that
        cannot run leaves the honest "no data" answer standing, instead of failing the turn.
        """
        if adapter is None:
            logger.warning(
                "[sql] latest-rows fallback skipped for store %s: no adapter is registered",
                storage_key,
            )
            return []
        try:
            query = adapter.build_timeseries_query(
                uuids=list(group_uuids),
                ts_col=ts_col,
                start_date=_FALLBACK_FLOOR,
                end_date=None,
                limit=limit,
            )
        except Exception as exc:
            logger.warning(
                "[sql] latest-rows fallback for store %s could not be built: %r",
                storage_key,
                exc,
            )
            return []
        if not query:
            logger.warning(
                "[sql] latest-rows fallback skipped for store %s: its adapter builds no "
                "timeseries query for these %d point(s)",
                storage_key,
                len(group_uuids),
            )
            return []
        logger.info(f"📝 Fallback query ({storage_key}): {str(query)[:200]}...")
        try:
            result = await adapter.execute_query(query)
        except Exception as exc:
            logger.warning("[sql] latest-rows fallback for store %s failed: %r", storage_key, exc)
            return []
        if not getattr(result, "success", False):
            logger.warning(
                "[sql] latest-rows fallback for store %s failed: %s",
                storage_key,
                getattr(result, "error", None) or "unsuccessful result",
            )
            return []
        return list(getattr(result, "data", None) or [])

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

    @staticmethod
    def _turn_uuids(state: Any) -> Set[str]:
        """The timeseries ids this turn has resolved so far, if any.

        Best-effort and never fatal: this runs on the fallback path, where the point is
        to keep the prompt proportional to the question rather than to guarantee a hit.
        Uses `contributing_uuids` rather than reading a key directly — `uuids` is
        documented as a bus key and nothing writes it, which is how every per-sensor
        source came out empty once already.
        """
        try:
            from orchestrator.services.evidence.assemble import contributing_uuids

            return set(contributing_uuids(getattr(state, "intermediate_results", {}) or {}))
        except Exception:  # pragma: no cover - the sampled shape is a fine fallback
            return set()

    async def _get_schema(self, keep_columns: Optional[Set[str]] = None) -> str:
        """Get schema text from the default adapter, naming the columns wanted."""
        return adapter_registry.get_schema_text(keep_columns=keep_columns)

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
                logger.warning(f"[sql_repair] Attempt {attempt} still failed: {last_error}")
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

        # V12-08 — a named calendar day is resolved by ONE function, the same one the
        # dialogue agent uses, so this fallback cannot disagree with the resolved interval
        # IN KIND.
        #
        # "yesterday" here used to read `now - timedelta(days=1)`, which is a DURATION.
        # Asked at 16:00 that names yesterday at 16:00, not yesterday's midnight boundary —
        # BUG-478's exact error, where a report headed "Yesterday" described a rolling
        # window half of which was today. This path only runs when no interval was resolved
        # upstream (see `_generate_sql`: `if not time_context`), so it never overrode a good
        # answer; but a fallback that is wrong in a DIFFERENT way from the primary is how
        # two sources of truth start disagreeing.
        #
        # The day word is passed literally rather than the whole question: a question naming
        # both days would otherwise resolve one of them twice, and dict ordering is not a
        # contract.
        for _word, _caption in (("today", "Today"), ("yesterday", "Yesterday")):
            if _word not in query_lower:
                continue
            _bounds = _day_bounds(_word, now)
            if _bounds:
                time_info += f"{_caption} runs {_bounds[0]} to {_bounds[1]} inclusive, in stored (UTC) time\n"

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

    @staticmethod
    def _row_span(rows: List[Dict[str, Any]]) -> Tuple[str, str]:
        """Earliest and latest timestamp actually present in these rows, as text.

        ("", "") when no row carries a readable timestamp. That is reported as an unknown
        span rather than silently omitted: a substitution whose period cannot be stated is
        MORE alarming than one whose period can, not less, and the reader has to be told
        which of the two they are looking at.
        """
        stamps: List[str] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            raw = row.get("timestamp")
            if raw is None:
                raw = row.get("Datetime") or row.get("datetime")
            if raw is None:
                continue
            if isinstance(raw, datetime):
                stamps.append(raw.isoformat(sep=" ", timespec="seconds"))
                continue
            text = str(raw).strip().replace("T", " ")
            if text:
                # Normalised so a store returning strings and one returning datetimes sort
                # against each other rather than into two disjoint orderings.
                stamps.append(text[:19])
        if not stamps:
            return "", ""
        return min(stamps), max(stamps)

    def _requested_window_label(self, start_date: Optional[str], end_date: Optional[str]) -> str:
        """The period the query actually asked for, in words.

        Derived through `_sanitize_datetime` — the same filter `_build_uuid_union_query`
        applies — so a bound the query DISCARDED (an unresolved relative phrase, say) is not
        named here as though it had been honoured.
        """
        start = self._sanitize_datetime(start_date if isinstance(start_date, str) else None)
        end = self._sanitize_datetime(end_date if isinstance(end_date, str) else None)
        if start and end:
            return f"{start} to {end}"
        if start:
            return f"the period from {start} onwards"
        if end:
            return f"the period up to {end}"
        return f"the last {DEFAULT_LOOKBACK_DAYS} days"

    def _sanitize_datetime(self, value: Optional[str]) -> Optional[str]:
        """Sanitize datetime strings to avoid SQL injection in deterministic queries."""
        if not value or not isinstance(value, str):
            return None
        import re

        v = value.strip().replace("T", " ")
        # Require a full calendar date, optionally with a time. A character-class
        # filter is too permissive: the remains of a relative phrase ("last 24
        # hours" → "-24") satisfy it and get spliced into the WHERE clause, where
        # MySQL silently matches nothing and Postgres reads it as a timezone.
        # Anything not an unambiguous timestamp is treated as absent so the
        # caller's default window applies.
        if re.match(r"^\d{4}-\d{2}-\d{2}([ ]\d{2}:\d{2}(:\d{2})?)?$", v):
            return v[:19]
        return None

    def _build_uuid_union_query(
        self,
        group_uuids: List[str],
        ts_col: str,
        start_date: Optional[str],
        end_date: Optional[str],
        limit: int = 1000,
        hour_predicate: str = "",
    ) -> str:
        """Build deterministic SQL for UUID columns using UNION ALL.

        ``hour_predicate`` (V6-T40) restricts rows to a recurring daily window — HourMask's
        dialect-neutral HOUR() clause. In the WHERE alongside the date bounds, because
        filtering after LIMIT would let daytime rows exhaust the cap before one night row
        arrived, which answers an overnight question with an empty set.
        """
        ts_safe = f"`{ts_col}`"
        start = self._sanitize_datetime(start_date)
        end = self._sanitize_datetime(end_date)

        time_clauses = []
        if hour_predicate:
            time_clauses.append(hour_predicate)
        if start:
            time_clauses.append(f"{ts_safe} >= '{start}'")
        elif not end:
            # No bounds at all — default to a recent lookback to prevent full table scans.
            # The SAME constant the substitution disclosure names, so the period the answer
            # says came back empty is the period the query actually asked for.
            time_clauses.append(
                f"{ts_safe} >= DATE_SUB(NOW(), INTERVAL {DEFAULT_LOOKBACK_DAYS} DAY)"
            )
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

        # 2. Check for forbidden keywords (DML/DDL) using WORD BOUNDARIES.
        # A substring check like "DELETE " (trailing space) is defeated by any other
        # whitespace — "DELETE\nFROM" / "DELETE\tFROM" would slip through. \b also
        # keeps the original intent of not flagging identifiers like "UPDATE_TIME"
        # (no boundary before the '_').
        import re

        forbidden_re = re.compile(
            r"\b(DROP|DELETE|INSERT|UPDATE|ALTER|TRUNCATE|GRANT|REVOKE|CREATE|REPLACE)\b",
            re.IGNORECASE,
        )
        match = forbidden_re.search(sql)
        if match:
            raise ValueError(f"Forbidden keyword detected: {match.group(1).upper()}")

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

    @staticmethod
    def _sensor_context(sensor_metadata: Optional[Dict[str, Dict[str, str]]]) -> str:
        """The label and unit for each uuid, as prompt context. "" when unknown.

        Says so explicitly when a sensor has no unit, because the instruction the
        prompt gives is "state the unit, or say it is not recorded" -- and a silent
        omission would let the model choose between those on its own.
        """
        if not sensor_metadata:
            return ""
        lines = ["", "Sensor information (use these names and units):"]
        for uuid, meta in sensor_metadata.items():
            label = (meta or {}).get("label") or uuid
            unit = ((meta or {}).get("unit") or "").strip()
            lines.append(
                f"  - {uuid} is '{label}'"
                + (f", measured in {unit}" if unit else ", unit NOT RECORDED")
            )
        lines.append("")
        return "\n".join(lines)

    async def _format_results(
        self,
        results: List[Dict[str, Any]],
        user_query: str,
        sql_query: str,
        sensor_metadata: Optional[Dict[str, Dict[str, str]]] = None,
    ) -> str:
        """Format SQL results into natural language.

        ``sensor_metadata`` carries each uuid's label and unit. Without it this
        prompt showed the model nothing but uuid/value/timestamp rows, so a filter
        differential pressure answered "152 - 154 units (the exact unit isn't
        specified)" -- an honest answer to a prompt that had omitted the unit, while
        the graph held it twice over (BUG-257). The caller has the metadata; it
        simply was never passed.
        """

        if not results:
            return "No data found for your query."

        # Convert results to readable format.
        #
        # TIMES IN THE BUILDING'S CLOCK (BUG-558). Stored readings are UTC (BUG-403) and went
        # into this prompt as UTC strings, so a demo answer read "509 ppm as of 02:20 UTC"
        # in a building where it was 03:20. Honest, and wrong for everyone reading it on
        # site. Converted here, deterministically, and labelled — never left to the model.
        import re

        from orchestrator.services.requested_interval import building_tz, to_local

        _tz = building_tz(getattr(settings, "BUILDING_ID", None))
        header = f"Found {len(results)} record(s)" + (
            f" (times are building local time, {_tz})" if _tz else ""
        )

        def _local(value: Any) -> Any:
            stamp = value if isinstance(value, datetime) else None
            if (
                stamp is None
                and isinstance(value, str)
                and re.match(r"^\d{4}-\d\d-\d\d[T ]\d\d:\d\d", value)
            ):
                try:
                    stamp = datetime.strptime(value.replace("T", " ")[:19], "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    stamp = None
            if stamp is None:
                return value
            return to_local(stamp.replace(tzinfo=None), _tz).strftime("%Y-%m-%d %H:%M:%S")

        # NEWEST FIRST, PROVED HERE RATHER THAN ASSUMED (run-3 row 120, 2026-09-17).
        #
        # The prompt below tells the model these rows are "the newest", and the slice below
        # took whatever order the rows arrived in. That holds while the lane's own
        # `ORDER BY timestamp DESC` survives — and it does not: `_coarsen` rebuckets the
        # readings when a privacy policy clamps resolution and emits them OLDEST FIRST.
        # A delta-T answer served at clamped resolution therefore opened "Latest snapshot
        # (2026-09-12 17:50:00)" over the FIRST reading of a window it then described as
        # running to 17 Sep, and called the circuit healthy on a five-day-old number.
        #
        # This is the BUG-520 shape at a second site: that one was fixed in the report
        # lane's `_summarize_readings`, which this lane does not use. Sorted by the row's
        # own timestamp, so the ten shown are the ten newest whatever produced them, and
        # rows whose time cannot be read keep their relative order at the end rather than
        # being promoted to "latest" by a failed comparison.
        def _sort_key(stamp: datetime) -> datetime:
            # Mixed naive/aware stamps raise on comparison. Every store here is UTC
            # (BUG-403), so dropping the offset orders them and changes no instant.
            return stamp.replace(tzinfo=None)

        _timed = [(self._row_time(r), r) for r in results]
        newest_at = ""
        if any(t is not None for t, _ in _timed):
            _with = [(t, r) for t, r in _timed if t is not None]
            _without = [r for t, r in _timed if t is None]
            _with.sort(key=lambda tr: _sort_key(tr[0]), reverse=True)
            results = [r for _, r in _with] + _without
            newest_at = str(_local(_with[0][0]))
        # SAY WHICH ROW IS THE LATEST; do not leave it to be inferred from position.
        if newest_at:
            header += (
                f", listed NEWEST FIRST — the most recent reading below is the one at {newest_at}"
            )
        result_text = header + ":\n\n"
        shown = results[:10]
        for i, row in enumerate(shown, 1):  # Limit to 10 rows
            result_text += f"{i}. "
            for key, value in row.items():
                if isinstance(value, datetime) or str(key).lower() in (
                    "timestamp",
                    "datetime",
                    "time",
                    "latest",
                    "latest_at",
                ):
                    value = _local(value)
                result_text += f"{key}: {value} | "
            result_text = result_text.rstrip(" | ") + "\n"

        if len(results) > 10:
            result_text += f"\n... and {len(results) - 10} more records"

        sensor_context = self._sensor_context(sensor_metadata)

        # STATISTICS OVER EVERY ROW, computed here (BUG-592). The prompt lists only the newest
        # ten rows, and a period question was answered from them: "over the past 24 hours ...
        # lowest 842 ppm at 17:23" while the store held 704 ppm at 04:08.
        all_rows_summary = ""
        if len(results) > 10:
            try:
                from orchestrator.services.series_summary import summarise_series

                all_rows_summary, _ = summarise_series(results, sensor_metadata or {}, _tz)
            except Exception as _ss_err:  # the rows still answer, less completely
                logger.debug(f"[sql_agent] series summary skipped: {_ss_err}")
        stats_block = (
            "\nStatistics over ALL "
            + str(len(results))
            + " records (computed by the system; the listed records are only the newest):\n"
            + all_rows_summary
            + "\n"
            if all_rows_summary
            else ""
        )

        # Generate natural language summary
        summary_prompt = f"""Convert these SQL query results into a natural language response.

User Query: {user_query}
{sensor_context}{stats_block}
Results:
{result_text}

Generate a concise, natural response that:
1. Directly answers the user's question
2. Highlights key statistics (averages, trends, etc.)
3. Uses clear, non-technical language
4. Mentions the time period if relevant
5. States the UNIT with every figure when the sensor information above gives one,
   and uses the sensor's readable name rather than its uuid. If no unit is given
   there, say the unit is not recorded - never invent one.
6. States times exactly as given above, which are already the building's local time -
   never convert them and never label them UTC.
6b. Calls a reading "latest", "current", "most recent" or "a snapshot" ONLY for the
   timestamp the header names as the most recent. The timestamp you print must be the
   one belonging to the value you print. If you are not showing that reading, do not
   use any of those words.
7. When statistics over all records are given above, every average, minimum, maximum,
   range and period comes from them, and the period is the one they state (from - to),
   not the question's wording.

Response:"""

        try:
            summary = await llm_manager.generate(summary_prompt, task_type=TaskType.GENERAL)
            return summary.strip()
        except Exception as e:
            logger.warning(f"[sql_agent] LLM summary generation failed, returning raw results: {e}")
            return result_text  # Fallback to raw results
