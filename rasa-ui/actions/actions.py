import os
import logging
import time
import requests
import pandas as pd
from rasa_sdk import Action
import numpy as np
import plotly.express as px
from rasa_sdk import Action, Tracker, FormValidationAction
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet
from rasa_sdk.types import DomainDict
from typing import Any, Text, Dict, List, Tuple, Union
from rasa_sdk.events import FollowupAction
from SPARQLWrapper import SPARQLWrapper, JSON
import mysql.connector
import json
import wave
import struct
import math
from ollama import Client
import dateparser
from dateparser.search import search_dates
from datetime import datetime, timedelta
import re
from calendar import monthrange
from decimal import Decimal
from dateutil.parser import parse

logger = logging.getLogger(__name__)

# -----------------------------
# Per-user artifact helpers
# -----------------------------
def sanitize_username(name: str) -> str:
    try:
        # Keep alphanumeric, dash and underscore only; cap length
        return "".join(c for c in (name or "") if c.isalnum() or c in ("-", "_"))[:64] or "anonymous"
    except Exception:
        return "anonymous"

def get_user_artifacts_dir(tracker: Tracker) -> Tuple[str, str]:
    """
    Compute a safe username from tracker.sender_id and ensure artifacts/<username> exists.
    Returns (user_safe, absolute_dir_path)
    """
    user_raw = getattr(tracker, "sender_id", None) or "anonymous"
    user_safe = sanitize_username(user_raw)
    user_dir = os.path.join(ARTIFACTS_DIR, user_safe)
    os.makedirs(user_dir, exist_ok=True)
    return user_safe, user_dir

# Ensure the shared data directory exists
SHARED_DIR = "/app/shared_data"
os.makedirs(SHARED_DIR, exist_ok=True)
# Single folder to keep all generated artifacts that are shared with users
ARTIFACTS_DIR = os.path.join(SHARED_DIR, "artifacts")
os.makedirs(ARTIFACTS_DIR, exist_ok=True)

# Logs directory: prefer a dedicated logs folder under shared_data so logs are visible on host
LOG_DIR = os.getenv("ACTION_LOG_DIR", os.path.join(SHARED_DIR, "logs"))
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "action.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),  # Save to file
        logging.StreamHandler(),  # Keep console output
    ],
)
logger = logging.getLogger(__name__)

# Global constants
# Default to internal Docker DNS names so services work inside the compose network.
nl2sparql_url = os.getenv("NL2SPARQL_URL", "http://nl2sparql:6005/nl2sparql")
FUSEKI_URL = os.getenv("FUSEKI_URL", "http://jena-fuseki-rdf-store:3030/abacws-sensor-network/sparql")
# Where to write downloadable files. Use the shared volume so http_server can serve them.
# Route everything through a single folder for easy sharing and cleanup.
ATTACHMENTS_DIR = ARTIFACTS_DIR
# Base URL for the simple HTTP server that exposes shared_data
BASE_URL_DEFAULT = "http://localhost:8080"
SUMMARIZATION_URL = os.getenv("SUMMARIZATION_URL", "http://ollama:11434")


MyDatabase = "MySQL_DB_CONFIG"
MySQL_DB_CONFIG = {
    "host": "host.docker.internal",
    "database": "sensordb",
    "user": "root",
    "password": "root",
    "port": "3306",
}

# Load VALID_SENSOR_TYPES from sensor_list.txt
try:
    # In the built image, files reside under /app; with WORKDIR=/app, use relative paths.
    # Prefer sensor_list.txt in current dir; fallback to legacy ./actions path if needed.
    candidates = [
        os.path.join(os.getcwd(), "sensor_list.txt"),
        os.path.join(os.getcwd(), "actions", "sensor_list.txt"),
    ]
    path = next((p for p in candidates if os.path.exists(p)), None)
    with open(path or "sensor_list.txt", "r") as f:
        VALID_SENSOR_TYPES = {line.strip() for line in f if line.strip()}
    logger.info(f"Loaded {len(VALID_SENSOR_TYPES)} sensor types from sensor_list.txt")
except FileNotFoundError:
    logger.error("sensor_list.txt not found in data/ directory")
    VALID_SENSOR_TYPES = set()
except Exception as e:
    logger.error(f"Error loading sensor_list.txt: {e}")
    VALID_SENSOR_TYPES = set()
# Initialize Ollama client
try:
    client = Client(host=SUMMARIZATION_URL)
    logger.info(f"Initialized Ollama client for {SUMMARIZATION_URL}")
except Exception as e:
    logger.error(f"Failed to initialize Ollama client: {e}")
    client = None


class ValidateSensorForm(FormValidationAction):
    def name(self) -> Text:
        return "validate_sensor_form"

    async def validate_sensor_type(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        # Handle comma-separated string input
        if isinstance(slot_value, str) and "," in slot_value:
            sensor_types = [s.strip() for s in slot_value.split(",")]
            logger.info(f"Split comma-separated input into: {sensor_types}")
        # Handle single string input
        elif isinstance(slot_value, str):
            sensor_types = [slot_value]
        # Handle list input (already a list)
        else:
            sensor_types = slot_value if isinstance(slot_value, list) else [slot_value]
            
        sensor_mappings = self.load_sensor_mappings()
        valid_sensors = [s for s in sensor_types if s in sensor_mappings]

        if not valid_sensors:
            dispatcher.utter_message(response="utter_ask_sensor_type")
            return {"sensor_type": None}
        
        logger.info(f"Validated sensor_types: {valid_sensors}")
        return {"sensor_type": valid_sensors}

    def load_sensor_mappings(self) -> Dict[str, str]:
        mappings = {}
        try:
            candidates = [
                os.path.join(os.getcwd(), "sensor_mappings.txt"),
                os.path.join(os.getcwd(), "actions", "sensor_mappings.txt"),
            ]
            path = next((p for p in candidates if os.path.exists(p)), None)
            with open(path or "sensor_mappings.txt", "r") as f:
                for line_num, line in enumerate(f, 1):
                    try:
                        if line.strip():
                            parts = line.strip().split(",")
                            if len(parts) == 2:
                                name, uuid = parts
                                # Store both directions for flexible lookup
                                mappings[name] = uuid  # For validation of names
                                mappings[uuid] = name  # For converting UUIDs to names
                            else:
                                logger.warning(f"Line {line_num}: Invalid format - expected 'name,uuid' but got: {line.strip()}")
                    except Exception as e:
                        logger.error(f"Error on line {line_num}: {e}")
            logger.info(f"Loaded {len(mappings)} sensor mappings")
        except FileNotFoundError:
            logger.error("sensor_mappings.txt not found")
            # Create an empty file to prevent future errors
            try:
                os.makedirs("./actions", exist_ok=True)
                with open("./actions/sensor_mappings.txt", "w") as f:
                    f.write("# Format: sensor_name,sensor_uuid\n")
                logger.info("Created empty sensor_mappings.txt file")
            except Exception as e:
                logger.error(f"Failed to create empty sensor_mappings.txt: {e}")
        return mappings

def extract_date_range(text: str) -> Dict[str, str]:
    """
    Extract date ranges from text using various common patterns.
    
    Args:
        text: The text to extract date ranges from
        
    Returns:
        Dictionary with 'start_date' and 'end_date' if found, empty dict otherwise
    """
    patterns = [
        # from DD/MM/YYYY to DD/MM/YYYY
        r"from\s+(\d{2}/\d{2}/\d{4})\s+to\s+(\d{2}/\d{2}/\d{4})",
        # between DD/MM/YYYY and DD/MM/YYYY
        r"between\s+(\d{2}/\d{2}/\d{4})\s+and\s+(\d{2}/\d{2}/\d{4})",
        # DD/MM/YYYY - DD/MM/YYYY
        r"(\d{2}/\d{2}/\d{4})\s*[-–—]\s*(\d{2}/\d{2}/\d{4})",
        # YYYY-MM-DD to YYYY-MM-DD
        r"(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})",
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return {
                'start_date': match.group(1),
                'end_date': match.group(2)
            }
    
    return {}

class ValidateDatesForm(FormValidationAction):
    def name(self) -> Text:
        return "validate_dates_form"

    async def validate_start_date(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        # Log the raw value received
        logger.info(f"Raw start_date input: '{slot_value}', type: {type(slot_value).__name__}")
        
        try:
            # Check message for dates in "from X to Y" format
            latest_message = tracker.latest_message.get("text", "")
            if latest_message:
                # Look for "from DD/MM/YYYY to DD/MM/YYYY" pattern
                date_match = re.search(r"from\s+(\d{2}/\d{2}/\d{4})\s+to\s+(\d{2}/\d{2}/\d{4})", latest_message)
                if date_match:
                    extracted_start = date_match.group(1)
                    extracted_end = date_match.group(2)
                    logger.info(f"Extracted dates from text: start={extracted_start}, end={extracted_end}")
                    
                    # Store end_date for later use
                    if not tracker.get_slot("end_date"):
                        dispatcher.utter_message(text=f"I've noted the end date as {extracted_end}")
                        tracker.slots["end_date"] = extracted_end
                    
                    # Use the extracted start date
                    slot_value = extracted_start
                    logger.info(f"Using start_date from text extraction: {slot_value}")
            
            # Handle various input formats
            
            # 1. Handle Duckling entity extraction which can return a dictionary
            if isinstance(slot_value, dict) and "value" in slot_value:
                slot_value = slot_value["value"]
                logger.info(f"Extracted value from Duckling dict: {slot_value}")
            
            # 2. Handle list of values (Duckling sometimes returns a list)
            if isinstance(slot_value, list) and len(slot_value) > 0:
                logger.info(f"start_date is a list: {slot_value}")
                slot_value = slot_value[0]
                
            # 3. Clean up text input (remove prefixes like "from", etc.)
            if isinstance(slot_value, str):
                slot_value = re.sub(r'^(from|start|on|date\s*:?)\s*', '', slot_value.strip(), flags=re.IGNORECASE)
                logger.info(f"Cleaned start_date input: '{slot_value}'")
            
            # 4. Handle multiple date formats
            if isinstance(slot_value, str):
                # 4.1. DD/MM/YYYY format
                if re.match(r"^\d{2}/\d{2}/\d{4}$", slot_value):
                    logger.info(f"start_date matched DD/MM/YYYY format: {slot_value}")
                    day, month, year = slot_value.split('/')
                    formatted_date = f"{year}-{month}-{day}"
                    parse(formatted_date)  # Validate
                    sql_date = formatted_date
                    logger.info(f"Converted to SQL date format: {sql_date}")
                    return {"start_date": slot_value}
                    
                # 4.2. YYYY-MM-DD format
                elif re.match(r"^\d{4}-\d{2}-\d{2}$", slot_value):
                    logger.info(f"start_date is already in YYYY-MM-DD format: {slot_value}")
                    parse(slot_value)  # Validate
                    sql_date = slot_value
                    return {"start_date": sql_date}
                    
                # 4.3. Try natural language parsing for other formats
                else:
                    logger.info(f"Trying to parse start_date with dateparser: {slot_value}")
                    parsed_date = dateparser.parse(slot_value)
                    if parsed_date:
                        formatted_date = parsed_date.strftime("%d/%m/%Y")
                        logger.info(f"Successfully parsed to: {formatted_date}")
                        return {"start_date": formatted_date}
                    else:
                        # Try with dateutil's parse as fallback
                        logger.info(f"Trying to parse start_date with dateutil: {slot_value}")
                        parsed = parse(slot_value)
                        formatted_date = parsed.strftime("%d/%m/%Y") 
                        logger.info(f"Successfully parsed with dateutil to: {formatted_date}")
                        return {"start_date": formatted_date}
            
            logger.error(f"Could not parse start_date value: {slot_value}")
            dispatcher.utter_message(text="I couldn't understand that date format. Please use DD/MM/YYYY (e.g., 01/02/2025).")
            return {"start_date": None}
            
        except ValueError as e:
            logger.error(f"start_date validation error: {e}, value: {slot_value}")
            dispatcher.utter_message(text="Invalid start date format. Please use DD/MM/YYYY.")
            return {"start_date": None}
        except Exception as e:
            logger.error(f"Unexpected error validating start_date: {str(e)}")
            dispatcher.utter_message(text="There was a problem processing the date. Please try again with format DD/MM/YYYY.")
            return {"start_date": None}

    async def validate_end_date(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        # Log the raw value received
        logger.info(f"Raw end_date input: '{slot_value}', type: {type(slot_value).__name__}")
        
        try:
            # Check message for dates in "from X to Y" format
            latest_message = tracker.latest_message.get("text", "")
            if latest_message:
                # Look for "from DD/MM/YYYY to DD/MM/YYYY" pattern
                date_match = re.search(r"from\s+(\d{2}/\d{2}/\d{4})\s+to\s+(\d{2}/\d{2}/\d{4})", latest_message)
                if date_match and not tracker.get_slot("start_date"):
                    extracted_start = date_match.group(1)
                    extracted_end = date_match.group(2)
                    logger.info(f"Extracted dates from text: start={extracted_start}, end={extracted_end}")
                    
                    # Store start_date for later use
                    dispatcher.utter_message(text=f"I've noted the start date as {extracted_start}")
                    tracker.slots["start_date"] = extracted_start
                    
                    # Use the extracted end date
                    slot_value = extracted_end
                    logger.info(f"Using end_date from text extraction: {slot_value}")
            
            # Handle various input formats
            
            # 1. Handle Duckling entity extraction which can return a dictionary
            if isinstance(slot_value, dict) and "value" in slot_value:
                slot_value = slot_value["value"]
                logger.info(f"Extracted value from Duckling dict: {slot_value}")
            
            # 2. Handle list of values (Duckling sometimes returns a list)
            if isinstance(slot_value, list) and len(slot_value) > 0:
                logger.info(f"end_date is a list: {slot_value}")
                slot_value = slot_value[0]
                
            # 3. Clean up text input (remove prefixes like "to", etc.)
            if isinstance(slot_value, str):
                slot_value = re.sub(r'^(to|end|until|through)\s*', '', slot_value.strip(), flags=re.IGNORECASE)
                logger.info(f"Cleaned end_date input: '{slot_value}'")
            
            # 4. Handle multiple date formats
            if isinstance(slot_value, str):
                # 4.1. DD/MM/YYYY format
                if re.match(r"^\d{2}/\d{2}/\d{4}$", slot_value):
                    logger.info(f"end_date matched DD/MM/YYYY format: {slot_value}")
                    day, month, year = slot_value.split('/')
                    formatted_date = f"{year}-{month}-{day}"
                    end_dt = parse(formatted_date)  # Validate
                    sql_date = formatted_date
                    logger.info(f"Converted to SQL date format: {sql_date}")
                    
                # 4.2. YYYY-MM-DD format
                elif re.match(r"^\d{4}-\d{2}-\d{2}$", slot_value):
                    logger.info(f"end_date is already in YYYY-MM-DD format: {slot_value}")
                    end_dt = parse(slot_value)  # Validate
                    sql_date = slot_value
                    
                # 4.3. Try natural language parsing for other formats
                else:
                    logger.info(f"Trying to parse end_date with dateparser: {slot_value}")
                    parsed_date = dateparser.parse(slot_value)
                    if parsed_date:
                        sql_date = parsed_date.strftime("%Y-%m-%d")
                        end_dt = parsed_date
                        slot_value = parsed_date.strftime("%d/%m/%Y")
                        logger.info(f"Successfully parsed to: {slot_value}, SQL format: {sql_date}")
                    else:
                        # Try with dateutil's parse as fallback
                        logger.info(f"Trying to parse end_date with dateutil: {slot_value}")
                        end_dt = parse(slot_value)
                        slot_value = end_dt.strftime("%d/%m/%Y")
                        sql_date = end_dt.strftime("%Y-%m-%d")
                        logger.info(f"Successfully parsed with dateutil to: {slot_value}, SQL format: {sql_date}")
                
                # Compare with start_date to ensure end_date is later
                start_date = tracker.get_slot("start_date")
                if start_date:
                    logger.info(f"Comparing with start_date: {start_date}")
                    
                    # Parse start_date in the same way
                    if re.match(r"^\d{2}/\d{2}/\d{4}$", start_date):
                        day, month, year = start_date.split('/')
                        formatted_start = f"{year}-{month}-{day}"
                        start_dt = parse(formatted_start)
                    elif re.match(r"^\d{4}-\d{2}-\d{2}$", start_date):
                        start_dt = parse(start_date)
                    else:
                        # Try with dateparser
                        parsed_start = dateparser.parse(start_date)
                        if parsed_start:
                            start_dt = parsed_start
                        else:
                            start_dt = parse(start_date)
                    
                    logger.info(f"start_dt: {start_dt}, end_dt: {end_dt}")
                    if end_dt <= start_dt:
                        dispatcher.utter_message(text="End date must be after start date.")
                        return {"end_date": None}
                
                logger.info(f"end_date validation successful: {slot_value}")
                return {"end_date": slot_value}
            
            logger.error(f"Could not parse end_date value: {slot_value}")
            dispatcher.utter_message(text="I couldn't understand that date format. Please use DD/MM/YYYY (e.g., 05/02/2025).")
            return {"end_date": None}
            
        except ValueError as e:
            logger.error(f"end_date validation error: {e}, value: {slot_value}")
            dispatcher.utter_message(text="Invalid end date format. Please use DD/MM/YYYY.")
            return {"end_date": None}
        except Exception as e:
            logger.error(f"Unexpected error validating end_date: {str(e)}")
            dispatcher.utter_message(text="There was a problem processing the date. Please try again with format DD/MM/YYYY.")
            return {"end_date": None}

class ActionQuestionToBrickbot(Action):
    def name(self) -> Text:
        return "action_question_to_brickbot"

    def load_sensor_mappings(self) -> Dict[str, str]:
        mappings = {}
        try:
            with open("./actions/sensor_mappings.txt", "r") as f:
                for line in f:
                    if line.strip():
                        name, uuid = line.strip().split(",")
                        mappings[uuid] = name
            logger.info(f"Loaded {len(mappings)} sensor mappings")
        except FileNotFoundError:
            logger.error("sensor_mappings.txt not found")
        return mappings

    def query_service_requests(self, url: str, data: Dict) -> Dict:
            headers = {"Content-Type": "application/json"}
            try:
                response = requests.post(url, json=data, headers=headers, timeout=20)
                response.raise_for_status()
                return response.json()
            except requests.exceptions.RequestException as e:
                logger.error(f"Failed to query nl2sparql endpoint: {e}")
                return {"error": str(e)}

    def add_sparql_prefixes(self, sparql_query: str) -> str:
        """
        Appends a set of predefined SPARQL prefixes to the query.
        """
        prefixes = [
            "PREFIX brick: <https://brickschema.org/schema/Brick#>",
            "PREFIX dcterms: <http://purl.org/dc/terms/>",
            "PREFIX owl: <http://www.w3.org/2002/07/owl#>",
            "PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>",
            "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>",
            "PREFIX sh: <http://www.w3.org/ns/shacl#>",
            "PREFIX skos: <http://www.w3.org/2004/02/skos/core#>",
            "PREFIX sosa: <http://www.w3.org/ns/sosa/>",
            "PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>",
            "PREFIX tag: <https://brickschema.org/schema/BrickTag#>",
            "PREFIX bldg: <http://abacwsbuilding.cardiff.ac.uk/abacws#>",
            "PREFIX bsh: <https://brickschema.org/schema/BrickShape#>",
            "PREFIX s223: <http://data.ashrae.org/standard223#>",
            "PREFIX bacnet: <http://data.ashrae.org/bacnet/2020#>",
            "PREFIX g36: <http://data.ashrae.org/standard223/1.0/extensions/g36#>",
            "PREFIX qkdv: <http://qudt.org/vocab/dimensionvector/>",
            "PREFIX quantitykind: <http://qudt.org/vocab/quantitykind/>",
            "PREFIX qudt: <http://qudt.org/schema/qudt/>",
            "PREFIX rec: <https://w3id.org/rec#>",
            "PREFIX ref: <https://brickschema.org/schema/Brick/ref#>",
            "PREFIX s223tobrick: <https://brickschema.org/extension/brick_extension_interpret_223#>",
            "PREFIX schema1: <http://schema.org/>",
            "PREFIX unit: <http://qudt.org/vocab/unit/>",
            "PREFIX vcard: <http://www.w3.org/2006/vcard/ns#>",
        ]
        return "\n".join(prefixes) + "\n" + sparql_query

    def execute_sparql_query(self, sparql_query: str) -> Dict:
        """
        Executes the given SPARQL query against the Fuseki endpoint.
        """
        sparql = SPARQLWrapper(FUSEKI_URL)
        sparql.setQuery(sparql_query)
        sparql.setReturnFormat(JSON)
        sparql.setTimeout(10)
        try:
            results = sparql.queryAndConvert()
            logger.info("SPARQL query executed successfully.")
            return results
        except Exception as e:
            logger.error(f"Error executing SPARQL query: {e}")
            return None

    def format_sparql_results(self, results: Dict) -> Text:
        """
        Formats SPARQL results for user-friendly summary display.
        """
        if (
            not results
            or "results" not in results
            or "bindings" not in results["results"]
        ):
            return "No results found."
        bindings = results["results"]["bindings"]
        if not bindings:
            return "No results found."
        formatted = []
        for binding in bindings:
            values = {key: val["value"] for key, val in binding.items()}
            formatted.append(f"Result: {values}")
        return "\n".join(formatted)[:500]

    def format_json_for_ui(self, json_data: Dict) -> Text:
            """
            Formats JSON for display in the chatbot UI.
            """
            try:
                json_str = json.dumps(json_data, indent=2)
                if len(json_str) > 1000:
                    json_str = json_str[:997] + "..."
                return f"Standardized JSON response:\n```json\n{json_str}\n```"
            except (TypeError, ValueError) as e:
                logger.error(f"Error formatting JSON for UI: {e}")
                return "Unable to display JSON response."

    def replace_uuids_with_sensor_types(self, data: Any, uuid_to_sensor: Dict[Text, Text]) -> Any:
                """Recursively replace UUIDs with sensor types in the data structure."""
                if isinstance(data, dict):
                    return {k: self.replace_uuids_with_sensor_types(v, uuid_to_sensor) for k, v in data.items()}
                elif isinstance(data, list):
                    return [self.replace_uuids_with_sensor_types(item, uuid_to_sensor) for item in data]
                elif isinstance(data, str) and data in uuid_to_sensor:
                    return uuid_to_sensor[data]
                return data

    def get_prefix_map(self) -> Dict[str, str]:
            """
            Returns a mapping of prefixes to URIs from add_sparql_prefixes.
            """
            prefixes = [
                ("brick", "https://brickschema.org/schema/Brick#"),
                ("dcterms", "http://purl.org/dc/terms/"),
                ("owl", "http://www.w3.org/2002/07/owl#"),
                ("rdf", "http://www.w3.org/1999/02/22-rdf-syntax-ns#"),
                ("rdfs", "http://www.w3.org/2000/01/rdf-schema#"),
                ("sh", "http://www.w3.org/ns/shacl#"),
                ("skos", "http://www.w3.org/2004/02/skos/core#"),
                ("sosa", "http://www.w3.org/ns/sosa/"),
                ("xsd", "http://www.w3.org/2001/XMLSchema#"),
                ("tag", "https://brickschema.org/schema/BrickTag#"),
                ("bldg", "http://abacwsbuilding.cardiff.ac.uk/abacws#"),
                ("bsh", "https://brickschema.org/schema/BrickShape#"),
                ("s223", "http://data.ashrae.org/standard223#"),
                ("bacnet", "http://data.ashrae.org/bacnet/2020#"),
                ("g36", "http://data.ashrae.org/standard223/1.0/extensions/g36#"),
                ("qkdv", "http://qudt.org/vocab/dimensionvector/"),
                ("quantitykind", "http://qudt.org/vocab/quantitykind/"),
                ("qudt", "http://qudt.org/schema/qudt/"),
                ("rec", "https://w3id.org/rec#"),
                ("ref", "https://brickschema.org/schema/Brick/ref#"),
                ("s223tobrick", "https://brickschema.org/extension/brick_extension_interpret_223#"),
                ("schema1", "http://schema.org/"),
                ("unit", "http://qudt.org/vocab/unit/"),
                ("vcard", "http://www.w3.org/2006/vcard/ns#"),
            ]
            return {uri: prefix for prefix, uri in prefixes}
    def standardize_sparql_json(
        self, results: Dict, user_question: str, sensor_type: str
    ) -> Dict:
        """
        Converts SPARQL JSON to a standardized format with prefixed URIs.
        """
        prefix_map = self.get_prefix_map()
        standardized = {"question": user_question, "sensor": sensor_type, "results": []}

        if (
            not results
            or "results" not in results
            or "bindings" not in results["results"]
        ):
            return standardized

        bindings = results["results"]["bindings"]
        for binding in bindings:
            result_entry = {}
            for key, val in binding.items():
                value_type = val.get("type")
                value = val.get("value", "")
                if value_type == "uri":
                    for uri, prefix in prefix_map.items():
                        if value.startswith(uri):
                            value = f"{prefix}:{value[len(uri):]}"
                            break
                elif value_type == "literal":
                    lang = val.get("xml:lang")
                    if lang:
                        value = f"{value}@{lang}"
                result_entry[key] = value
            standardized["results"].append(result_entry)

        return standardized


    def summarize_response(self, standardized_json: Dict) -> Text:
        """
        Generate a summary using the Mistral model based on the standardized JSON.

        :param standardized_json: Dict containing question, sensor, and results from SPARQL.
        :return: A short summary as a string or None if an error occurs.
        """
        if not client:
            logger.error("Ollama client is not initialized.")
            return None
            
        # Add detailed logging of input data
        logger.info("======== SUMMARY INPUT DATA (ActionQuestionToBrickbot) ========")
        logger.info(f"Input data type: {type(standardized_json).__name__}")
        
        # Log sensor information
        sensor_info = standardized_json.get("sensor", "No sensor info")
        logger.info(f"Sensor info: {sensor_info}")
        
        # Load sensor mappings once and reuse
        sensor_mappings = self.load_sensor_mappings()
        logger.info(f"Loaded {len(sensor_mappings)} sensor mappings")
        
        # Check for UUIDs and their mappings in the data
        uuid_pattern = re.compile(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}')
        json_str = json.dumps(standardized_json)
        uuids_found = uuid_pattern.findall(json_str)
        
        if uuids_found:
            logger.info(f"UUIDs found in SPARQL data: {uuids_found}")
            # Check if we have mappings for these UUIDs
            for uuid in uuids_found:
                if uuid in sensor_mappings:
                    logger.info(f"UUID {uuid} maps to sensor name: {sensor_mappings[uuid]}")
                    # Consider replacing UUID with sensor name in the data before sending to LLM
                else:
                    logger.info(f"UUID {uuid} has no mapping in sensor_mappings.txt")
        
        # Log a sample of the JSON (truncated if too large)
        sample_json = json.dumps(standardized_json, indent=2)
        if len(sample_json) > 500:
            logger.info(f"Data sample (truncated): {sample_json[:500]}...")
        else:
            logger.info(f"Data sample: {sample_json}")
        logger.info("===============================================================")

        question = standardized_json.get("question", "")
        
        # Replace any UUIDs with sensor names in the data before generating the prompt
        processed_json = standardized_json
        if uuids_found and sensor_mappings:
            processed_json = self.replace_uuids_with_sensor_types(standardized_json, sensor_mappings)
            logger.info("Replaced UUIDs with sensor names in data for summary")
        
        sparql_response = json.dumps(processed_json, indent=2)
        logger.debug(f"Summarization input - question: {question}")
        logger.debug(f"Summarization input - SPARQL response: {sparql_response}")

        prompt = (
            "Instructions: Read the following smart building data received over an ontology created using BrickSchema "
            "and SQL sensor data or analytics output received and provide a short summary.\n"
            f"Question: {question}\n"
            f"SPARQL Response: {sparql_response}\n\n"
            "Explanation:"
        )
        logger.debug(f"Generated prompt: {prompt}")

        try:
            logger.debug(
                "Sending prompt to the model 'mistral:latest' with max_tokens=150"
            )
            response = client.generate(
                model="mistral:latest", prompt=prompt, options={"max_tokens": 150}
            )
            logger.debug(f"Response received: {response}")

            if "response" not in response:
                error_message = (
                    "Error: The response does not contain the 'response' key."
                )
                logger.error(error_message)
                return None

            summary = response["response"]
            logger.debug(f"Extracted summary: {summary}")
            return summary

        except Exception as e:
            logger.exception(f"An error occurred while generating the summary: {e}")
            return None

    async def run(
            self,
            dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any],
        ) -> List[Dict[Text, Any]]:
            user_question = tracker.latest_message.get("text", "").strip()
            if not user_question:
                dispatcher.utter_message(text="Sorry, I couldn't understand your query. Please try again.")
                return [SlotSet("sparql_error", True)]

            sensor_types = tracker.get_slot("sensor_type") or []
            logger.info(f"User question: {user_question}, Sensor types: {sensor_types}")

            sensor_mappings = self.load_sensor_mappings()
            uuids = [sensor_mappings.get(sensor) for sensor in sensor_types if sensor in sensor_mappings]

            if not sensor_types or not uuids:
                dispatcher.utter_message(response="utter_ask_sensor_type")
                return [{"event": "active_loop", "name": "sensor_form"}, SlotSet("sparql_error", False)]

            entity_string = ", ".join([f"bldg:{sensor}" for sensor in sensor_types])
            input_data = {"question": user_question, "entity": entity_string}
            logger.info(f"Input data for nl2sparql: {input_data}")
            dispatcher.utter_message(text="Processing your query...")

            response = self.query_service_requests(os.getenv("NL2SPARQL_URL", "https://deep-gator-cleanly.ngrok-free.app/nl2sparql"), input_data)
            if "error" in response:
                dispatcher.utter_message(response="utter_translation_error")
                return [SlotSet("sparql_error", True), SlotSet("timeseries_ids", None)]

            sparql_query = response.get("sparql_query")
            if not sparql_query:
                dispatcher.utter_message(text="No valid SPARQL query returned. Please try again.")
                return [SlotSet("sparql_error", True), SlotSet("timeseries_ids", None)]

            logger.info(f"Generated SPARQL query: {sparql_query}")
            full_sparql_query = self.add_sparql_prefixes(sparql_query)
            sparql_results = self.execute_sparql_query(full_sparql_query)
            if sparql_results is None:
                dispatcher.utter_message(text="Error executing SPARQL query. Please try again later.")
                return [SlotSet("sparql_error", True), SlotSet("timeseries_ids", None)]

            formatted_results = self.format_sparql_results(sparql_results)
            dispatcher.utter_message(text=f"SPARQL query results:\n{formatted_results}")

            standardized_json = self.standardize_sparql_json(sparql_results, user_question, sensor_types[0] if sensor_types else "")
            base_url = os.getenv("BASE_URL", BASE_URL_DEFAULT)
            user_safe, user_dir = get_user_artifacts_dir(tracker)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"sparql_response_{timestamp}.json"
            output_file = os.path.join(user_dir, filename)
            try:
                with open(output_file, "w") as f:
                    json.dump(standardized_json, f, indent=2)
                json_url = f"{base_url}/artifacts/{user_safe}/{filename}"
                dispatcher.utter_message(
                    text="SPARQL results saved as JSON:",
                    attachment={"type": "json", "url": json_url, "filename": filename}
                )
            except (IOError, TypeError) as e:
                logger.error(f"Failed to save SPARQL JSON: {e}")
                dispatcher.utter_message(text="Error saving SPARQL results. Inline results above.")

            uuid_pattern = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
            timeseries_ids = [
                r.get("timeseriesId") for r in standardized_json.get("results", [])
                if r.get("timeseriesId") and uuid_pattern.match(r.get("timeseriesId"))
            ]
            has_timeseries = bool(timeseries_ids)
            logger.info(f"Has timeseries IDs: {has_timeseries}, IDs: {timeseries_ids}")
            # Add these helpful debug logs
            logger.info(f"Deciding path - has_timeseries: {has_timeseries}, start_date: {tracker.get_slot('start_date')}, end_date: {tracker.get_slot('end_date')}")
            logger.info(f"Will proceed to {'timeseries processing' if has_timeseries else 'direct summary'} path")
            is_auto_date = False
            now = datetime.now()
            today_str = now.strftime("%Y-%m-%d")
            today_time_str = now.strftime("%Y-%m-%d %H:%M:%S")
            midnight_str = f"{today_str} 00:00:00"

            # After extracting timeseries_ids:
            events = [SlotSet("sparql_error", False)]
            if has_timeseries:
                events.append(SlotSet("timeseries_ids", timeseries_ids))
                dispatcher.utter_message(text=f"Found timeseries IDs: {timeseries_ids}")
            
                # Add these lines to define the missing variables
                start_date = tracker.get_slot("start_date")
                end_date = tracker.get_slot("end_date")

                # Add after checking if both dates are present
                if start_date and end_date:
                    # Initialize SQL date variables
                    start_date_sql = None
                    end_date_sql = None
                    
                    # Convert any ISO format dates to SQL format before returning
                    if 'T' in start_date:
                        parsed_date = parse(start_date)
                        start_date_sql = parsed_date.strftime("%Y-%m-%d %H:%M:%S")
                        events.append(SlotSet("start_date", start_date_sql))
                        logger.info(f"Converted ISO start_date to SQL format: {start_date_sql}")
                    else:
                        # Keep the original if not ISO format
                        start_date_sql = start_date
                        
                    if 'T' in end_date:
                        parsed_date = parse(end_date)
                        end_date_sql = parsed_date.strftime("%Y-%m-%d %H:%M:%S")
                        events.append(SlotSet("end_date", end_date_sql))
                        logger.info(f"Converted ISO start_date to SQL format: {end_date_sql}")
                    else:
                        end_date_sql = end_date
                       
                    
                    # Add right before the summary is generated (around line 741):
                    logger.info("==================== Date Debug Information ====================")
                    logger.info(f"Final tracker start_date before summarization: {tracker.get_slot('start_date')}")
                    logger.info(f"Final tracker end_date before summarization: {tracker.get_slot('end_date')}")
                    logger.info(f"Final start_date before summarization: {start_date_sql if 'start_date_sql' in locals() else tracker.get_slot('start_date')}")
                    logger.info(f"Final end_date before summarization: {end_date_sql if 'end_date_sql' in locals() else tracker.get_slot('end_date')}")
                    logger.info(f"Auto-generated dates: {is_auto_date}")
                    logger.info("===============================================================")

                    # summary = self.summarize_response(standardized_json)
                    # if summary:
                    #     logger.info(f"Generated SPARQL summary: {summary}")
                    #     dispatcher.utter_message(text=f"Summary: {summary}")
                    # else:
                    #     logger.debug("No summary generated for SPARQL results")

                    return events
                else:
                    # If dates are missing, use the form to collect them
                    dispatcher.utter_message(response="utter_ask_start_date")
                    events.append({"event": "active_loop", "name": "dates_form"})
                    return events
            else:
                # Instead of always asking for dates, first check if dates are already available
                start_date = tracker.get_slot("start_date")
                end_date = tracker.get_slot("end_date")
                
                # If dates are available, summarize the SPARQL results
                if start_date and end_date:
                    logger.info(f"No timeseries IDs found, but dates are available. Generating summary from SPARQL results.")
                    # Generate summary directly from standardized_json without timeseries processing
                    summary = self.summarize_response(standardized_json)
                    if summary:
                        logger.info(f"Generated SPARQL summary (without timeseries): {summary}")
                        dispatcher.utter_message(text=f"Summary: {summary}")
                    else:
                        logger.debug("No summary generated for SPARQL results")
                        dispatcher.utter_message(text="I found information based on your query, but couldn't generate a summary.")
                else:
                    # If no dates, ask for them (original behavior)
                    dispatcher.utter_message(response="utter_ask_start_date")
                    events.append({"event": "active_loop", "name": "dates_form"})
                
                return events
            
class ActionDebugEntities(Action):
    def name(self) -> Text:
        return "action_debug_entities"
        
    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        # Gather all latest message data
        latest_message = tracker.latest_message
        
        # Log the entire message for debugging
        logger.info(f"Latest message: {json.dumps(latest_message, indent=2)}")
        
        # Extract and display entities
        entities = latest_message.get("entities", [])
        entity_text = "Extracted entities:\n" + json.dumps(entities, indent=2)
        logger.info(entity_text)
        dispatcher.utter_message(text=entity_text)
        
        # Check for date entities specifically
        date_entities = [e for e in entities if e.get("entity") == "time"]
        if date_entities:
            dates_text = "Date entities found:\n" + json.dumps(date_entities, indent=2)
            dispatcher.utter_message(text=dates_text)
            logger.info(dates_text)
        else:
            dispatcher.utter_message(text="No date entities found!")
            logger.info("No date entities found!")
            
        # Show current slot values
        dispatcher.utter_message(text=f"Current start_date: {tracker.get_slot('start_date')}")
        dispatcher.utter_message(text=f"Current end_date: {tracker.get_slot('end_date')}")
        
        return []

class ActionProcessTimeseries(Action):
    def name(self) -> Text:
        return "action_process_timeseries"

    def fetch_sql_data(
        self,
        timeseries_ids: Union[str, List[str]],
        start_date: str,
        end_date: str,
        database: str,
        table_name: str,
        db_config: Dict,
        return_json: bool = True
    ) -> Tuple[Union[str, Dict], Union[str, None]]:
        """
        Fetches sensor data for multiple timeseries IDs and dates dynamically.

        Parameters:
            timeseries_ids: Single UUID or list of UUIDs (e.g., '249a4c9c-fe31-4649-a119-452e5e8e7dc5').
            start_date: Start timestamp as a string, e.g., '2025-02-10 00:00:00'.
            end_date: End timestamp as a string, e.g., '2025-02-20 23:59:59'.
            database: Name of the database (e.g., 'sensordb').
            table_name: Name of the table (e.g., 'sensor_data').
            db_config: Dictionary containing database connection parameters (host, user, password, etc.).
            return_json: If True, returns results as a JSON string; otherwise, returns a Python dict.

        Returns:
            A tuple (results, error) where error is None if successful. Results are formatted as:
            {
                "timeseriesId_1": [
                    {"datetime": "2025-02-10 05:31:59", "reading_value": 27.99},
                    ...
                ],
                "timeseriesId_2": [
                    {"datetime": "2025-02-10 06:00:00", "reading_value": 28.10},
                    ...
                ],
                ...
            }
        """
        
        try:   
            # Ensure timeseries_ids is a list
            if isinstance(timeseries_ids, str):
                timeseries_ids = [timeseries_ids]
        
            # Validate inputs
            if not timeseries_ids or not all(isinstance(tid, str) for tid in timeseries_ids):
                return None, "Invalid or empty timeseries_ids provided"
            if not start_date or not end_date:
                return None, "Start_date and end_date must be provided"
            if not database or not table_name:
                return None, "Database and table_name must be provided"

            # Establish database connection
            connection = mysql.connector.connect(**db_config)
            if not connection.is_connected():
                return None, "Failed to connect to the database"

            cursor = connection.cursor(dictionary=True)
            results = {}

            # Construct dynamic SQL query
            # Select Datetime and all timeseries IDs as columns
            columns = ["Datetime"] + [f"`{tid}`" for tid in timeseries_ids]
            columns_str = ", ".join(columns)

            # Construct WHERE clause to ensure non-NULL values for all timeseries IDs
            where_conditions = [f"`{tid}` IS NOT NULL" for tid in timeseries_ids]
            where_conditions.append("Datetime BETWEEN %s AND %s")
            where_clause = " AND ".join(where_conditions)

            # Build the full query
            query = f"""
                SELECT {columns_str}
                FROM `{database}`.`{table_name}`
                WHERE {where_clause}
            """

            # Execute query with parameters
            cursor.execute(query, (start_date, end_date))
            rows = cursor.fetchall()

            # Initialize results dictionary
            for tid in timeseries_ids:
                results[tid] = []

            # Process each row
            for row in rows:
                dt_value = row.get("Datetime")
                if dt_value and hasattr(dt_value, "strftime"):
                    dt_value = dt_value.strftime("%Y-%m-%d %H:%M:%S")

                # Add data for each timeseries ID
                for tid in timeseries_ids:
                    reading_value = row.get(tid)
                    if reading_value is not None:
                        # Convert Decimal to float if necessary
                        if isinstance(reading_value, Decimal):
                            reading_value = float(reading_value)
                        results[tid].append(
                            {"datetime": dt_value, "reading_value": reading_value}
                        )

            # Clean up
            cursor.close()
            connection.close()

            # Return results in the requested format
            if return_json:
                return json.dumps(results, indent=4), None
            return results, None

        except mysql.connector.Error as e:
            logger.error(f"MySQL error: {e}")
            return None, f"MySQL error: {str(e)}"
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            return None, f"Unexpected error: {str(e)}"

    def load_sensor_mappings(self) -> Dict[str, str]:
        mappings = {}
        try:
            with open("./actions/sensor_mappings.txt", "r") as f:
                for line_num, line in enumerate(f, 1):
                    try:
                        if line.strip():
                            parts = line.strip().split(",")
                            if len(parts) == 2:
                                name, uuid = parts
                                # Store both directions for flexible lookup
                                mappings[name] = uuid  # For validation of names
                                mappings[uuid] = name  # For converting UUIDs to names
                            else:
                                logger.warning(f"Line {line_num}: Invalid format - expected 'name,uuid' but got: {line.strip()}")
                    except Exception as e:
                        logger.error(f"Error on line {line_num}: {e}")
            logger.info(f"Loaded {len(mappings)} sensor mappings")
        except FileNotFoundError:
            logger.error("sensor_mappings.txt not found")
            # Create an empty file to prevent future errors
            try:
                os.makedirs("./actions", exist_ok=True)
                with open("./actions/sensor_mappings.txt", "w") as f:
                    f.write("# Format: sensor_name,sensor_uuid\n")
                logger.info("Created empty sensor_mappings.txt file")
            except Exception as e:
                logger.error(f"Failed to create empty sensor_mappings.txt: {e}")
        return mappings

    def replace_uuids_with_sensor_types(self, data: Any, uuid_to_sensor: Dict[Text, Text]) -> Any:
            """Recursively replace UUIDs with sensor types in the data structure."""
            if isinstance(data, dict):
                return {k: self.replace_uuids_with_sensor_types(v, uuid_to_sensor) for k, v in data.items()}
            elif isinstance(data, list):
                return [self.replace_uuids_with_sensor_types(item, uuid_to_sensor) for item in data]
            elif isinstance(data, str) and data in uuid_to_sensor:
                return uuid_to_sensor[data]
            return data

    def query_analytics_type(self, url: str, prompt: str) -> List[str]:
            """Query the T5 model endpoint to retrieve analytics types."""
            headers = {"Content-Type": "application/json"}
            payload = {"prompt": prompt}
            try:
                response = requests.post(url, json=payload, headers=headers, timeout=20)
                response.raise_for_status()
                analytics_types = response.json()
                if isinstance(analytics_types, list):
                    return analytics_types
                logger.error(f"Unexpected response format from T5 endpoint: {analytics_types}")
                return []
            except requests.exceptions.RequestException as e:
                logger.error(f"Failed to query T5 endpoint: {e}")
                return []

    def summarize_response(self, standardized_json: Dict) -> Text:
        """
        Generate a summary using the Mistral model based on the standardized JSON.

        :param standardized_json: Dict containing question, sensor, and results from analytics.
        :return: A short summary as a string or None if an error occurs.
        """
        if not client:
            logger.error("Ollama client is not initialized.")
            return None
            
        # Add detailed logging of input data
        logger.info("======== SUMMARY INPUT DATA (ActionProcessTimeseries) ========")
        logger.info(f"Input data type: {type(standardized_json).__name__}")
        
        # Check if this is analytics response data
        if "analysis_type" in standardized_json:
            logger.info(f"Analysis type: {standardized_json.get('analysis_type')}")
        
        # Check for UUIDs and their mappings in the data
        uuid_pattern = re.compile(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}')
        json_str = json.dumps(standardized_json)
        uuids_found = uuid_pattern.findall(json_str)
        
        # Load sensor mappings once and reuse
        sensor_mappings = self.load_sensor_mappings()
        logger.info(f"Loaded {len(sensor_mappings)} sensor mappings")
        
        if uuids_found:
            logger.info(f"UUIDs found in analytics data: {uuids_found}")
            # Check if we have mappings for these UUIDs
            for uuid in uuids_found:
                if uuid in sensor_mappings:
                    logger.info(f"UUID {uuid} maps to sensor name: {sensor_mappings[uuid]}")
                else:
                    logger.info(f"UUID {uuid} has no mapping in sensor_mappings.txt")
        
        # Log a sample of the JSON (truncated if too large)
        sample_json = json.dumps(standardized_json, indent=2)
        if len(sample_json) > 500:
            logger.info(f"Data sample (truncated): {sample_json[:500]}...")
        else:
            logger.info(f"Data sample: {sample_json}")
        logger.info("===============================================================")

        question = standardized_json.get("question", "")
        
        # Replace any UUIDs with sensor names in the data before generating the prompt
        processed_json = standardized_json
        if uuids_found and sensor_mappings:
            processed_json = self.replace_uuids_with_sensor_types(standardized_json, sensor_mappings)
            logger.info("Replaced UUIDs with sensor names in data for summary")
            
        sparql_response = json.dumps(processed_json, indent=2)
        logger.debug(f"Summarization input - question: {question}")
        logger.debug(f"Summarization input - analytics response: {sparql_response}")
    async def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        timeseries_ids = tracker.get_slot("timeseries_ids") or []
        start_date = tracker.get_slot("start_date")
        end_date = tracker.get_slot("end_date")
        sensor_types = tracker.get_slot("sensor_type") or []
        
        # Detailed logging of received values
        logger.info("==================== ActionProcessTimeseries.run ====================")
        logger.info(f"Timeseries IDs: {timeseries_ids}")
        logger.info(f"Raw start_date: '{start_date}', type: {type(start_date).__name__}")
        logger.info(f"Raw end_date: '{end_date}', type: {type(end_date).__name__}")
        logger.info(f"Sensor types: {sensor_types}")
        logger.info("=====================================================================")
        
        # Debug the entire tracker slots
        logger.info("All slots in tracker:")
        for slot_name, slot_value in tracker.slots.items():
            if slot_value is not None:
                logger.info(f"  {slot_name}: {slot_value} ({type(slot_value).__name__})")
        logger.info(f"Timeseries IDs: {timeseries_ids}, Start date: {start_date}, End date: {end_date}, Sensor types: {sensor_types}")
       # Inside ActionProcessTimeseries class, modify the date processing part in run() method
        try:
            # Initialize before date parsing
            start_date_sql = None
            end_date_sql = None
            # Log the date formats received
            logger.info(f"Processing dates - start: {start_date}, end: {end_date}")
            
            # Handle empty or None values
            if not start_date:
                dispatcher.utter_message(response="utter_ask_start_date")
                return [{"event": "active_loop", "name": "dates_form"}]
                
            if not end_date:
                dispatcher.utter_message(response="utter_ask_end_date")
                return [{"event": "active_loop", "name": "dates_form"}]
            #  NEW CODE: Handle Duckling dictionary format with from/to values
            if isinstance(start_date, dict) and 'from' in start_date:
                start_date = start_date['from']
                logger.info(f"Extracted 'from' value from start_date dictionary: {start_date}")
            
            if isinstance(end_date, dict) and 'to' in end_date:
                end_date = end_date['to']
                logger.info(f"Extracted 'to' value from end_date dictionary: {end_date}")
            # Convert start_date to SQL datetime format (YYYY-MM-DD HH:MM:SS)
            if isinstance(start_date, str):
                # Handle ISO 8601 format (2025-04-29T05:05:00.000+01:00)
                if 'T' in start_date:
                    # Parse using dateutil which handles ISO 8601 well
                    parsed_date = parse(start_date)
                    start_date_sql = parsed_date.strftime("%Y-%m-%d %H:%M:%S")
                    logger.info(f"Converted ISO start_date '{start_date}' to SQL format: '{start_date_sql}'")
                # Handle DD/MM/YYYY format
                elif re.match(r"^\d{2}/\d{2}/\d{4}$", start_date):
                    day, month, year = start_date.split('/')
                    start_date_sql = f"{year}-{month}-{day} 00:00:00"
                    logger.info(f"Converted start_date '{start_date}' to SQL format: '{start_date_sql}'")
                # Handle YYYY-MM-DD format
                elif re.match(r"^\d{4}-\d{2}-\d{2}$", start_date):
                    start_date_sql = f"{start_date} 00:00:00"
                    logger.info(f"Added time to start_date: '{start_date_sql}'")
                # Try parsing any other format
                else:
                    parsed_date = dateparser.parse(start_date)
                    if parsed_date:
                        start_date_sql = parsed_date.strftime("%Y-%m-%d %H:%M:%S")
                        logger.info(f"Parsed start_date '{start_date}' to SQL format: '{start_date_sql}'")
                    else:
                        # Last resort: try with dateutil
                        parsed_date = parse(start_date)
                        start_date_sql = parsed_date.strftime("%Y-%m-%d %H:%M:%S")
                        logger.info(f"Parsed start_date with dateutil to: '{start_date_sql}'")
            
            # Convert end_date to SQL datetime format (YYYY-MM-DD HH:MM:SS)
            if isinstance(end_date, str):
                # Handle ISO 8601 format (2025-04-29T05:05:00.000+01:00)
                if 'T' in end_date:
                    # Parse using dateutil which handles ISO 8601 well
                    parsed_date = parse(end_date)
                    end_date_sql = parsed_date.strftime("%Y-%m-%d %H:%M:%S")
                    logger.info(f"Converted ISO end_date '{end_date}' to SQL format: '{end_date_sql}'")
                # Handle DD/MM/YYYY format
                elif re.match(r"^\d{2}/\d{2}/\d{4}$", end_date):
                    day, month, year = end_date.split('/')
                    end_date_sql = f"{year}-{month}-{day} 23:59:59"
                    logger.info(f"Converted end_date '{end_date}' to SQL format with end of day: '{end_date_sql}'")
                # Handle YYYY-MM-DD format
                elif re.match(r"^\d{4}-\d{2}-\d{2}$", end_date):
                    end_date_sql = f"{end_date} 23:59:59"
                    logger.info(f"Added end of day time to end_date: '{end_date_sql}'")
                # Try parsing any other format
                else:
                    parsed_date = dateparser.parse(end_date)
                    if parsed_date:
                        # For end date, we set time to end of day
                        end_date_sql = parsed_date.strftime("%Y-%m-%d 23:59:59")
                        logger.info(f"Parsed end_date '{end_date}' to SQL format with EOD: '{end_date_sql}'")
                    else:
                        # Last resort: try with dateutil
                        parsed_date = parse(end_date)
                        end_date_sql = parsed_date.strftime("%Y-%m-%d 23:59:59")
                        logger.info(f"Parsed end_date with dateutil to EOD: '{end_date_sql}'")
            # After all your date parsing logic:
            if start_date_sql is None or end_date_sql is None:
                logger.error("Failed to convert dates to SQL format")
                dispatcher.utter_message(text="There was an error processing the date formats.")
                return []
        except ValueError as e:
            logger.error(f"Error parsing dates: {e}")
            dispatcher.utter_message(text="Invalid date format. Please provide dates in DD/MM/YYYY format.")
            return []

        # Continue with the rest of the code using start_date_sql and end_date_sql
        db_config = {
            "host": os.getenv("DB_HOST", "host.docker.internal"),
            "database": os.getenv("DB_NAME", "sensordb"),
            "user": os.getenv("DB_USER", "root"),
            "password": os.getenv("DB_PASSWORD", "root"),
            "port": os.getenv("DB_PORT", "3306")
        }
        logger.info(f"SQL Query will use dates: {start_date_sql} to {end_date_sql}")
        sql_results, error = self.fetch_sql_data(
            timeseries_ids=timeseries_ids,
            start_date=start_date_sql,
            end_date=end_date_sql,
            database="sensordb",
            table_name="sensor_data",
            db_config=db_config,
            return_json=True
        )
        if error:
            logger.error(f"SQL query failed: {error}")
            dispatcher.utter_message(text=f"Failed to retrieve SQL data: {error}")
            return []
        if sql_results is None:
            logger.error("SQL query returned None results")
            dispatcher.utter_message(text="No data found for the specified timeseries IDs and date range.")
            return []

        dispatcher.utter_message(text="SQL query executed successfully.")
        base_url = os.getenv("BASE_URL", BASE_URL_DEFAULT)
        user_safe, user_dir = get_user_artifacts_dir(tracker)
        timestamp = int(time.time())
        filename = f"sql_results_{timestamp}.json"
        file_path = os.path.join(user_dir, filename)
        try:
            with open(file_path, "w") as f:
                json.dump(json.loads(sql_results), f, indent=2)
            json_url = f"{base_url}/artifacts/{user_safe}/{filename}"
            dispatcher.utter_message(
                text="SQL query results saved as JSON:",
                attachment={"type": "json", "url": json_url, "filename": filename}
            )
            # dispatcher.utter_message(text=f"SQL query results:\n{json.dumps(json.loads(sql_results), indent=2)}")
            logger.info(f"SQL results saved to {file_path}")
        except (IOError, TypeError) as e:
            logger.error(f"Failed to save SQL JSON: {e}")
            dispatcher.utter_message(text="Error saving SQL results. Inline results above.")

        # Analytics (optional) and summarization
        analytics_type = "analyze_device_deviation"
        logger.info(f"Using analytics_type: {analytics_type} (default for testing)")
        ANALYTICS_URL = os.getenv("ANALYTICS_URL", "")

        # Parse the SQL results from string to dictionary
        sql_results_dict = json.loads(sql_results)
        payload = {
            "analysis_type": analytics_type,
            **sql_results_dict  # Expand the dictionary directly into the payload
        }
        analytics_response = {"analysis_type": analytics_type, **sql_results_dict}
        if ANALYTICS_URL:
            try:
                resp = requests.post(ANALYTICS_URL, json=payload, timeout=30)
                try:
                    analytics_response = resp.json()
                    if "error" in analytics_response:
                        logger.error(f"Analytics error: {analytics_response['error']}")
                        dispatcher.utter_message(text=f"Analytics error: {analytics_response['error']}")
                    else:
                        dispatcher.utter_message(text="Analytics results:")
                        dispatcher.utter_message(text=json.dumps(analytics_response, indent=2))
                        logger.info(f"Analytics response: {analytics_response}")
                except ValueError as e:
                    logger.error(f"Invalid JSON response from analytics service: {e}")
                    dispatcher.utter_message(text="Error: Invalid response format from analytics service")
            except Exception as e:
                logger.error(f"Failed to query analytics service: {e}")
                dispatcher.utter_message(text="Error querying analytics service. Using SQL results for summary.")
        else:
            logger.info("ANALYTICS_URL not set. Skipping analytics call and summarizing SQL results directly.")

        # start performing pre-processing for summary
        uuid_to_sensor = self.load_sensor_mappings()
        if not uuid_to_sensor:
            dispatcher.utter_message(text="Error: Could not load sensor mappings. Using raw analytics data for summarization.")
        else:
            analytics_response = self.replace_uuids_with_sensor_types(analytics_response, uuid_to_sensor)
            logger.info(f"Modified analytics response with sensor types: {analytics_response}")

        # start performing summary
        summary = self.summarize_response(analytics_response)
        logger.info(f"Generated summary: {summary}")
        dispatcher.utter_message(text=f"Summary: {summary}" if summary else "Unable to generate summary.")

        return []

class ActionResetSlots(Action):
    def name(self) -> Text:
        return "action_reset_slots"

    async def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        return [
            SlotSet("sensor_type", None),
            SlotSet("start_date", None),
            SlotSet("end_date", None),
            SlotSet("timeseries_ids", None),
            SlotSet("request_dates", False),
            SlotSet("sparql_error", False),
        ]

# ---------------------------
# Action to test if the action server is working to give all format files
# ---------------------------
# Simple action to generate sample files in shared_data and share links
class ActionGenerateAndShareData(Action):
    def name(self) -> Text:
        return "action_generate_and_share_data"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        events: List[Dict[Text, Any]] = []
        base_url = os.getenv("BASE_URL", BASE_URL_DEFAULT)
        user_safe, user_dir = get_user_artifacts_dir(tracker)
        bundle_media = os.getenv("BUNDLE_MEDIA", "true").lower() in ("1", "true", "yes")
        media_items: List[Dict[str, str]] = []

        # 0) Generate sample downloadable files and share links (as attachments for frontend)
        try:
            os.makedirs(user_dir, exist_ok=True)
            now = datetime.now()
            rid = now.strftime("%Y%m%d_%H%M%S")
            json_name = f"report_{rid}.json"
            txt_name = f"placeholder_{rid}.txt"  # using text placeholder to avoid image libs
            json_path = os.path.join(user_dir, json_name)
            txt_path = os.path.join(user_dir, txt_name)

            payload = {
                "report_id": rid,
                "generated_on": now.isoformat(),
                "user_id": tracker.sender_id,
                "message": "Sample data report generated by action server.",
            }
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write("This is a placeholder for an image file. Replace with real content.")

            json_url = f"{base_url}/artifacts/{user_safe}/{json_name}"
            txt_url = f"{base_url}/artifacts/{user_safe}/{txt_name}"

            # Queue media items for a single bundled message
            media_items.append({"type": "json", "url": json_url, "filename": json_name})
            media_items.append({"type": "txt", "url": txt_url, "filename": txt_name})

            events.append(SlotSet("generated_urls", {"json": json_url, "file": txt_url}))
        except Exception as e:
            logger.exception("Failed to generate/share files: %s", e)
            dispatcher.utter_message(text="Error generating sample files.")

        # Log working directory
        try:
            logger.info(f"Working directory: {os.getcwd()}")
        except Exception:
            pass

        # 1) Include an example image
        media_items.append({
            "type": "image",
            "url": "https://picsum.photos/800/400",
            "filename": "sample.jpg",
        })

        # 2) Additional remote image
        media_items.append({
            "type": "image",
            "url": "https://picsum.photos/200/300",
            "filename": "dummy.jpg",
        })

        # 3) Remote PNG image
        media_items.append({
            "type": "image",
            "url": "https://file-examples.com/storage/feb797b78b68ccdb5a1194c/2017/10/file_example_PNG_500kB.png",
            "filename": "dummy.png",
        })

        # 4) Remote PDF example
        media_items.append({
            "type": "pdf",
            "url": "https://file-examples.com/wp-content/storage/2017/10/file-sample_150kB.pdf",
            "filename": "dummy.pdf",
        })

        # 5) Send a dummy CSV file (generated locally for download via local server)
        try:
            csv_name = f"sample_{int(time.time())}.csv"
            csv_path = os.path.join(user_dir, csv_name)
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write("timestamp,value\n")
                for i in range(5):
                    ts = (datetime.utcnow() - timedelta(minutes=5 - i)).strftime("%Y-%m-%d %H:%M:%S")
                    f.write(f"{ts},{round(np.random.rand(), 4)}\n")
            csv_url = f"{base_url}/artifacts/{user_safe}/{csv_name}"
            media_items.append({"type": "csv", "url": csv_url, "filename": csv_name})
        except Exception as e:
            logger.error(f"Failed to generate CSV: {e}")
            dispatcher.utter_message(text="Note: Could not generate CSV file.")

        # 6) Send dummy JSON data (as a downloadable local file)
        try:
            dummy_json_name = f"dummy_{int(time.time())}.json"
            dummy_json_path = os.path.join(user_dir, dummy_json_name)
            with open(dummy_json_path, "w", encoding="utf-8") as f:
                json.dump({"key": "value", "number": 123}, f, indent=2)
            dummy_json_url = f"{base_url}/artifacts/{user_safe}/{dummy_json_name}"
            media_items.append({"type": "json", "url": dummy_json_url, "filename": dummy_json_name})
        except Exception as e:
            logger.error(f"Failed to generate dummy JSON: {e}")
            dispatcher.utter_message(text="Note: Could not generate dummy JSON file.")

        # 7) Video: try downloading a small mp4 locally for playback via localhost
        try:
            video_name = f"sample_{int(time.time())}.mp4"
            video_path = os.path.join(user_dir, video_name)
            video_url_src = "https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/1080/Big_Buck_Bunny_1080_10s_1MB.mp4"
            resp = requests.get(video_url_src, stream=True, timeout=15)
            resp.raise_for_status()
            with open(video_path, "wb") as vf:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        vf.write(chunk)
            media_items.append({
                "type": "video",
                "url": f"{base_url}/artifacts/{user_safe}/{video_name}",
                "filename": video_name,
            })
        except Exception as e:
            logger.warning(f"Failed to download sample video locally: {e}. Falling back to remote URL")
            media_items.append({
                "type": "video",
                "url": "https://file-examples.com/storage/feb797b78b68ccdb5a1194c/2017/04/file_example_MP4_640_3MG.mp4",
                "filename": "dummy_video.mp4",
            })

        # 8) Dummy link
        media_items.append({
            "type": "link",
            "url": "https://www.wikipedia.org/",
            "filename": "dummy_link.html",
        })

        # 9) Generate a small WAV audio locally for reliable playback
        try:
            wav_name = f"sample_{int(time.time())}.wav"
            wav_path = os.path.join(user_dir, wav_name)
            framerate = 22050
            duration_sec = 2
            freq = 440.0  # A4 tone
            nframes = int(duration_sec * framerate)
            amp = 16000
            with wave.open(wav_path, 'w') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)  # 16-bit
                wf.setframerate(framerate)
                for i in range(nframes):
                    value = int(amp * math.sin(2 * math.pi * freq * (i / framerate)))
                    wf.writeframesraw(struct.pack('<h', value))
            media_items.append({
                "type": "audio",
                "url": f"{base_url}/artifacts/{user_safe}/{wav_name}",
                "filename": wav_name,
            })
        except Exception as e:
            logger.warning(f"Failed to generate local WAV: {e}. Falling back to remote MP3")
            media_items.append({
                "type": "audio",
                "url": "https://file-examples.com/storage/fe560e508068ccbf398f4e7/2017/11/file_example_WAV_1MG.wav",
                "filename": "Your_audio.mp3",
            })

        # 10) Generate and share chart (HTML) and optionally serve a PDF if present
        try:
            timestamps = pd.date_range(start="2025-01-01", periods=50, freq="min")
            sensor_values = np.random.rand(50)
            data = pd.DataFrame({"timestamp": timestamps, "sensor_value": sensor_values})
            fig = px.line(data, x="timestamp", y="sensor_value", title="Live Sensor Data")

            static_folder = user_dir
            os.makedirs(static_folder, exist_ok=True)

            chart_name = f"chart_{int(time.time())}.html"
            chart_path = os.path.join(static_folder, chart_name)
            fig.write_html(chart_path)
            logger.info(f"HTML chart saved at: {chart_path}")

            html_url = f"{base_url}/artifacts/{user_safe}/{chart_name}"
            # Queue chart as html and as simple link
            media_items.append({"type": "html", "url": html_url, "filename": chart_name})
            media_items.append({"type": "link", "url": html_url, "filename": chart_name})

            # PDF file handling (serve if a dummy file exists in shared folder)
            pdf_filename = "dummy.pdf"
            pdf_file_path = os.path.join(static_folder, pdf_filename)
            if os.path.exists(pdf_file_path):
                pdf_url = f"{base_url}/artifacts/{user_safe}/{pdf_filename}"
                logger.info(f"PDF file served from: {pdf_url}")
                media_items.append({"type": "pdf", "url": pdf_url, "filename": pdf_filename})
            else:
                logger.warning(f"PDF file {pdf_file_path} not found")
                # Optional notice; skip adding to media_items
        except Exception as e:
            logger.error(f"Error generating chart/PDF: {str(e)}")
            dispatcher.utter_message(text="Error: Could not generate or serve chart/PDF.")

        # Finally, send output according to toggle
        if media_items:
            if bundle_media:
                dispatcher.utter_message(
                    text="Yes. It is working as expected. Here are your generated artifacts shows you can successfully download and see them:",
                    json_message={"media": media_items},
                )
            else:
                dispatcher.utter_message(text="Generated artifacts:")
                for m in media_items:
                    # Prefer attachment objects for frontend rendering
                    dispatcher.utter_message(attachment=m)

        return events

