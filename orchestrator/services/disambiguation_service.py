"""
DisambiguationService – data-driven sensor clarification.

When a user says "sensor 5.12" or "readings from 5.28" without specifying a
sensor *type*, we query GraphDB for every sensor at that node and return a
structured "Did you mean…?" response so the user can pick the right one.
"""

import re
from typing import Any, Dict, List, Optional

import httpx

from shared.config import settings
from shared.utils import get_logger

logger = get_logger(__name__)

# Sensor type keywords that make a reference unambiguous
_TYPE_KEYWORDS = [
    "temperature",
    "co2",
    "humidity",
    "air quality",
    "occupancy",
    "pressure",
    "illuminance",
    "light",
    "tvoc",
    "voc",
    "formaldehyde",
    "pm1",
    "pm2",
    "pm10",
    "no2",
    "oxygen",
    "o2",
    "sound",
    "noise",
    "pir",
    "motion",
    "mq2",
    "mq3",
    "mq5",
    "mq9",
    "co level",
    "carbon monoxide",
    "combustible",
    "ethyl",
    "alcohol",
    "lpg",
    "natural gas",
]

# Patterns that indicate an ambiguous sensor reference:
#   "sensor 5.12"  /  "sensor_5.12"  /  "5.12 sensor"  /  "node 5.12"
_AMBIGUOUS_PATTERNS = [
    # "sensor 5.12" or "sensor_5.12"
    re.compile(
        r"\bsensor[_\s]+(\d+\.\d+)\b",
        re.IGNORECASE,
    ),
    # "5.12 sensor"
    re.compile(
        r"\b(\d+\.\d+)\s+sensor\b",
        re.IGNORECASE,
    ),
    # "node 5.12"
    re.compile(
        r"\bnode[_\s]+(\d+\.\d+)\b",
        re.IGNORECASE,
    ),
    # "readings from 5.12" / "data for 5.12"
    re.compile(
        r"\b(?:reading|data|value|reading|latest|current)\s+(?:from|for|at|in)\s+(\d+\.\d+)\b",
        re.IGNORECASE,
    ),
]

# Friendly display names for common Brick sensor classes
_CLASS_DISPLAY = {
    "Air_Temperature_Sensor": "Air Temperature Sensor",
    "CO2_Level_Sensor": "CO₂ Level Sensor",
    "Zone_Air_Humidity_Sensor": "Humidity Sensor",
    "Air_Quality_Level_Sensor": "Air Quality Level Sensor",
    "Air_Quality_Sensor": "Air Quality Sensor",
    "Occupancy_Sensor": "Occupancy / PIR Sensor",
    "pir_sensor": "PIR (Motion) Sensor",
    "Illuminance_Sensor": "Illuminance / Light Sensor",
    "TVOC_Level_Sensor": "TVOC Sensor",
    "Formaldehyde_Level_Sensor": "Formaldehyde Sensor",
    "PM1_Level_Sensor_Atmospheric": "PM1 Particulate Sensor",
    "PM2.5_Level_Sensor_Atmospheric": "PM2.5 Particulate Sensor",
    "PM10_Level_Sensor_Atmospheric": "PM10 Particulate Sensor",
    "NO2_Level_Sensor": "NO₂ Sensor",
    "CO_Level_Sensor": "CO Level Sensor",
    "Sound_Noise_Sensor_MEMS": "Sound / Noise Sensor",
    "Oxygen_O2_Percentage_Gas_Sensor": "O₂ Percentage Sensor",
    "Carbon_Monoxide_Coal_Gas_Liquefied_MQ9_Gas_Sensor": "CO/Coal Gas Sensor (MQ9)",
    "Combustible_Gas_Smoke_MQ2_Sensor": "Combustible Gas / Smoke Sensor (MQ2)",
    "Alcohol_Vapor_MQ3_Gas_Sensor": "Alcohol Vapor Sensor (MQ3)",
    "LPG_Natural_Gas_Town_MQ5_Gas_Sensor": "LPG / Natural Gas Sensor (MQ5)",
    "Ethyl_Alcohol_C2H5CH_Gas_Sensor": "Ethyl Alcohol Sensor",
}

# Sensor classes that commonly have time-series data in MySQL
# (shown first in the suggestion list)
_PRIMARY_SENSOR_TYPES = {
    "Air_Temperature_Sensor",
    "CO2_Level_Sensor",
    "Zone_Air_Humidity_Sensor",
    "Air_Quality_Level_Sensor",
    "Occupancy_Sensor",
    "pir_sensor",
    "Illuminance_Sensor",
    "TVOC_Level_Sensor",
    "PM2.5_Level_Sensor_Atmospheric",
}


class DisambiguationService:
    """
    Detects ambiguous sensor references in a user query and generates
    data-driven clarification messages with real GraphDB sensor candidates.
    """

    GRAPHDB_ENDPOINT = (
        f"http://{settings.GRAPHDB_HOST}:{settings.GRAPHDB_PORT}"
        f"/repositories/{settings.GRAPHDB_REPOSITORY}"
    )

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def extract_ambiguous_node(self, user_query: str) -> Optional[str]:
        """
        Return the node number (e.g. '5.12') if the query contains an
        ambiguous sensor reference, otherwise None.

        A reference is ambiguous when the user mentions a node number with
        the word 'sensor' / 'node' / 'reading' but WITHOUT a type keyword
        (temperature, CO2, humidity …).
        """
        uq = user_query.lower()

        # If the query already names a sensor type → not ambiguous
        if any(kw in uq for kw in _TYPE_KEYWORDS):
            return None

        for pattern in _AMBIGUOUS_PATTERNS:
            m = pattern.search(uq)
            if m:
                return m.group(1)  # e.g. "5.12"

        return None

    async def get_candidates(self, node_number: str) -> List[Dict[str, Any]]:
        """
        Query GraphDB for all sensors at bldg:Zone_{node_number}.
        Returns a list of dicts: {local_name, label, brick_class, uuid}
        sorted so primary sensor types appear first.

        We derive the sensor type from the sensor URI local name (e.g.
        "Air_Temperature_Sensor_5.12" → type "Air_Temperature_Sensor")
        to avoid GraphDB RDFS inference polluting ?type with parent classes.
        """
        bldg_ns = settings.BUILDING_NAMESPACE
        bldg_pfx = settings.BUILDING_PREFIX
        zone_ref = f"{bldg_pfx}:Zone_{node_number}"
        node_suffix = node_number.replace(".", "\\.")  # for regex

        # Query only the sensor URI + label + UUID — no ?type needed
        sparql = f"""
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
PREFIX ref:   <https://brickschema.org/schema/Brick/ref#>
PREFIX bldg:  <{bldg_ns}>

SELECT DISTINCT ?sensor ?label ?uuid WHERE {{
  ?sensor brick:hasLocation {zone_ref} .
  OPTIONAL {{ ?sensor rdfs:label ?label . }}
  OPTIONAL {{
    ?sensor ref:hasExternalReference ?ref .
    ?ref ref:hasTimeseriesId ?uuid .
  }}
  FILTER(STRSTARTS(STR(?sensor), '{bldg_ns}'))
}} ORDER BY ?sensor LIMIT 60
"""
        try:
            auth = (
                (settings.GRAPHDB_USER, settings.GRAPHDB_PASSWORD)
                if settings.GRAPHDB_USER
                else None
            )
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.post(
                    self.GRAPHDB_ENDPOINT,
                    auth=auth,
                    data={"query": sparql},
                    headers={"Accept": "application/sparql-results+json"},
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            logger.warning(f"DisambiguationService: GraphDB query failed: {e}")
            return []

        seen_locals: set = set()
        candidates: List[Dict[str, Any]] = []
        node_tag = f"_{node_number}"  # e.g. "_5.12"

        for b in data.get("results", {}).get("bindings", []):
            sensor_uri = b.get("sensor", {}).get("value", "")
            label_val = b.get("label", {}).get("value", "")
            uuid_val = b.get("uuid", {}).get("value", "")

            # local_name e.g. "Air_Temperature_Sensor_5.12"
            local_name = (
                sensor_uri.split("#")[-1] if "#" in sensor_uri else sensor_uri.split("/")[-1]
            )

            # De-duplicate by sensor local name (DISTINCT ?sensor already helps,
            # but multiple UUIDs per sensor can produce extra rows)
            if local_name in seen_locals:
                continue
            seen_locals.add(local_name)

            # Derive the sensor class from the local name by stripping "_5.XX" suffix
            # e.g. "Air_Temperature_Sensor_5.12" → "Air_Temperature_Sensor"
            if node_tag in local_name:
                brick_class = local_name[: local_name.rfind(node_tag)]
            else:
                # Fallback: strip trailing numeric suffix
                brick_class = re.sub(r"_[\d.]+$", "", local_name)

            display_name = _CLASS_DISPLAY.get(brick_class, brick_class.replace("_", " "))
            is_primary = brick_class in _PRIMARY_SENSOR_TYPES

            candidates.append(
                {
                    "local_name": local_name,
                    "label": label_val or local_name,
                    "brick_class": brick_class,
                    "display_name": display_name,
                    "uuid": uuid_val,
                    "is_primary": is_primary,
                }
            )

        # Primary sensor types first, then alphabetical
        candidates.sort(key=lambda c: (0 if c["is_primary"] else 1, c["display_name"]))
        return candidates

    def format_clarification(
        self,
        user_query: str,
        node_number: str,
        candidates: List[Dict[str, Any]],
    ) -> str:
        """
        Build a user-facing clarification message with numbered options.
        """
        if not candidates:
            return (
                f"I couldn't find any sensors at node **{node_number}**. "
                f"Please check the zone number and try again."
            )

        # Group by primary vs secondary
        primary = [c for c in candidates if c.get("is_primary")]
        secondary = [c for c in candidates if not c.get("is_primary")]

        lines = [
            f"I found **{len(candidates)} sensors** at node **{node_number}**. "
            f"Could you tell me which one you mean?\n"
        ]

        if primary:
            lines.append("**Common sensors (time-series data available):**")
            for i, c in enumerate(primary, 1):
                lines.append(f"{i}. **{c['display_name']}**")
        if secondary:
            lines.append("\n**Other sensors at this node:**")
            offset = len(primary)
            for i, c in enumerate(secondary, offset + 1):
                lines.append(f"{i}. {c['display_name']}")

        # Build example rephrasings from primary sensor types
        examples = []
        for c in primary[:3]:
            kw = (
                c["brick_class"]
                .replace("Air_Temperature_Sensor", "temperature")
                .replace("CO2_Level_Sensor", "CO2")
                .replace("Zone_Air_Humidity_Sensor", "humidity")
                .replace("Air_Quality_Level_Sensor", "air quality")
                .replace("Illuminance_Sensor", "light")
                .replace("TVOC_Level_Sensor", "TVOC")
                .replace("pir_sensor", "occupancy")
                .replace("_", " ")
                .lower()
            )
            examples.append(f'"What is the **{kw}** reading for zone {node_number}?"')

        if examples:
            lines.append("\nFor example, try asking: " + " or ".join(examples))

        return "\n".join(lines)

    async def check_and_clarify(
        self,
        user_query: str,
    ) -> Optional[str]:
        """
        Entry point: returns a clarification string if the query is ambiguous,
        or None if it is unambiguous and normal processing should continue.
        """
        node = self.extract_ambiguous_node(user_query)
        if node is None:
            return None

        logger.info(f"[disambiguation] Ambiguous sensor ref detected — node {node}")
        candidates = await self.get_candidates(node)
        msg = self.format_clarification(user_query, node, candidates)
        return msg


# Module-level singleton
_disambiguation_service: Optional[DisambiguationService] = None


def get_disambiguation_service() -> DisambiguationService:
    global _disambiguation_service
    if _disambiguation_service is None:
        _disambiguation_service = DisambiguationService()
    return _disambiguation_service
