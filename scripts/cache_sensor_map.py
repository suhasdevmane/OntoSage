import sys
import os
import json
import asyncio
import httpx
from typing import Dict, Any

# Add project root to path
sys.path.append(os.getcwd())

from shared.config import settings
from shared.utils import get_logger

logger = get_logger("sensor_mapper")

GRAPHDB_QUERY_ENDPOINT = f"http://{settings.GRAPHDB_HOST}:{settings.GRAPHDB_PORT}/repositories/{settings.GRAPHDB_REPOSITORY}"

QUERY_ALL_SENSORS = """
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX bldg: <http://abacwsbuilding.cardiff.ac.uk/abacws#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX ashrae: <http://data.ashrae.org/standard223#>
PREFIX ref: <https://brickschema.org/schema/Brick/ref#>

SELECT ?sensor ?label ?uuid ?storage WHERE {
    ?sensor rdf:type/rdfs:subClassOf* brick:Sensor .
    OPTIONAL { ?sensor rdfs:label ?label . }
    ?sensor ashrae:hasExternalReference ?extRef .
    ?extRef ref:hasTimeseriesId ?uuid ;
            ref:storedAt ?storage .
}
"""

async def fetch_sensor_map():
    logger.info(f"Connecting to GraphDB at {GRAPHDB_QUERY_ENDPOINT}...")
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        auth = (settings.GRAPHDB_USER, settings.GRAPHDB_PASSWORD) if settings.GRAPHDB_USER else None
        
        try:
            response = await client.post(
                GRAPHDB_QUERY_ENDPOINT,
                auth=auth,
                data={"query": QUERY_ALL_SENSORS},
                headers={"Accept": "application/sparql-results+json"}
            )
            response.raise_for_status()
            results = response.json()
            
            bindings = results.get("results", {}).get("bindings", [])
            logger.info(f"Found {len(bindings)} sensors with external references.")
            
            sensor_map = {}
            
            for b in bindings:
                sensor_uri = b["sensor"]["value"]
                # Extract local name (e.g. Air_Temperature_Sensor_5.04)
                local_name = sensor_uri.split("#")[-1]
                
                uuid = b["uuid"]["value"]
                storage = b["storage"]["value"]
                label = b.get("label", {}).get("value", local_name)
                
                entry = {
                    "uri": sensor_uri,
                    "uuid": uuid,
                    "storage": storage,
                    "label": label
                }
                
                # Map by local name (most common lookup)
                sensor_map[local_name] = entry
                # Map by label
                sensor_map[label] = entry
                # Map by URI
                sensor_map[sensor_uri] = entry
                
            # Save to file
            os.makedirs("data", exist_ok=True)
            with open("data/sensor_map.json", "w", encoding="utf-8") as f:
                json.dump(sensor_map, f, indent=2)
                
            logger.info(f"Saved {len(sensor_map)} keys to data/sensor_map.json")
            return True
            
        except Exception as e:
            logger.error(f"Failed to fetch sensor map: {e}")
            return False

if __name__ == "__main__":
    # Setup basic logging if not using structured
    import logging
    logging.basicConfig(level=logging.INFO)
    
    asyncio.run(fetch_sensor_map())
