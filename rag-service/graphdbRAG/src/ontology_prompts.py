"""
Ontology-specific GraphRAG Entity Extraction
Customized prompt templates for RDF/Turtle ontology processing
"""
from langchain_core.prompts import ChatPromptTemplate
from typing import List


def create_ontology_entity_extraction_prompt(entity_types: List[str]) -> ChatPromptTemplate:
    """
    Create a prompt template for extracting entities and relationships from RDF ontology triples
    
    Args:
        entity_types: List of entity types from the ontology (e.g., TemperatureSensor, HVAC, etc.)
    
    Returns:
        ChatPromptTemplate configured for ontology entity extraction
    """
    
    entity_types_str = ", ".join(entity_types)
    
    # Define delimiters as actual strings (not template variables)
    TUPLE_DELIMITER = "<|>"
    RECORD_DELIMITER = "##"
    COMPLETION_DELIMITER = "<|COMPLETE|>"
    
    prompt_template = f"""
Given RDF triples from a building ontology (Turtle/TTL format) and a list of entity types from Brick, BOT, SAREF schemas, identify all entities and relationships while preserving RDF prefixes and namespaces for accurate SPARQL query generation.

Use these exact delimiters in your output:

You MUST preserve entity identifiers EXACTLY as they appear in the input triples:
1. Do NOT convert underscores to spaces (keep `Formaldehyde_Level_Sensor_5_05` if that is the exact identifier)
2. Do NOT change case (respect original capitalization)
3. Do NOT add or remove characters, spaces, or punctuation
4. Do NOT singularize/pluralize or otherwise normalize labels
5. Prefixed names (e.g., `bldg:Formaldehyde_Level_Sensor_5.05`) must remain identical
If a sensor appears as `bldg:Formaldehyde_Level_Sensor_5.05` in a triple, you MUST output `bldg:Formaldehyde_Level_Sensor_5.05` (not a spaced version like `FORMALDEHYDE LEVEL SENSOR 5.05`).
If there is any ambiguity, choose the verbatim subject/object string from the triple.

1. Identify all entities from the RDF triples. For each identified entity, extract the following information:
Format each entity as ("entity"{TUPLE_DELIMITER}<entity_name>{TUPLE_DELIMITER}<entity_type>{TUPLE_DELIMITER}<entity_description>{TUPLE_DELIMITER}<namespace_prefix>)

2. From the RDF triples, identify all relationships (predicates connecting subjects to objects).
For each relationship, extract the following information:
Format each relationship as ("relationship"{TUPLE_DELIMITER}<source_entity>{TUPLE_DELIMITER}<target_entity>{TUPLE_DELIMITER}<relationship_predicate>{TUPLE_DELIMITER}<relationship_description>{TUPLE_DELIMITER}<relationship_strength>)

3. Return output as a single list of all entities and relationships using ONLY the specified delimiters. Do NOT insert extra blank lines or commentary.

4. Preserve all RDF prefixes AND the local part of the identifier exactly (including underscores and periods) as they appear (brick:, bot:, saref:, bldg:, etc.) - these are critical for SPARQL generation.

5. EXTERNAL TIMESERIES REFERENCE EXTRACTION:
When an entity is a sensor, setpoint, device, or any point whose real-world value/history/analysis would be retrieved from an external time series database, always include its external timeseries reference alongside the entity tuple, if present in the TTL input, even if the user did not explicitly ask for any external references for further database queries.

Specifically, if the TTL includes an ExternalReference blank node linked via predicates such as `ashrae:hasExternalReference` or `ref:hasExternalReference`, and that node has `ref:hasTimeseriesId` and `ref:storedAt`, you must surface both values.

Example Pattern (TTL):
- Entity subject: bldg:CO_Level_Sensor_5.06
  linked to _:genid179 with type `ref:TimeseriesReference`,
  having `ref:hasTimeseriesId "791284f8-..."` and `ref:storedAt bldg:database1`.

Required Output (in addition to standard entity/relationship tuples):
- External Reference tuple:
  ("external_timeseries"{TUPLE_DELIMITER}<entity_name>{TUPLE_DELIMITER}<timeseries_id>{TUPLE_DELIMITER}<stored_at>)
  Where:
    - entity_name: exact TTL identifier of the entity (e.g., bldg:CO_Level_Sensor_5.06)
    - timeseries_id: exact literal value from `ref:hasTimeseriesId`
    - stored_at: exact identifier from `ref:storedAt`

Do not fabricate IDs or storage locations. Only report references that exist in the TTL chunk.

6. When finished, output {COMPLETION_DELIMITER}.

######################

Example 1:

entity_types: [TemperatureSensor, Zone, Room, HVAC, AHU, Point, Equipment]
text:
RDF Triples:
bldg:TempSensor_R101 rdf:type brick:Temperature_Sensor .
bldg:TempSensor_R101 brick:isPointOf bldg:AHU_01 .
bldg:AHU_01 rdf:type brick:AHU .
bldg:AHU_01 brick:feeds bldg:Zone_West .
bldg:Zone_West rdf:type brick:HVAC_Zone .
output:
("entity"{TUPLE_DELIMITER}bldg:TempSensor_R101{TUPLE_DELIMITER}TemperatureSensor{TUPLE_DELIMITER}A temperature sensor located in Room 101, measuring air temperature as a point of AHU_01{TUPLE_DELIMITER}bldg){RECORD_DELIMITER}
("entity"{TUPLE_DELIMITER}bldg:AHU_01{TUPLE_DELIMITER}AHU{TUPLE_DELIMITER}Air Handling Unit 01, an HVAC equipment that serves the west zone and has multiple sensor points{TUPLE_DELIMITER}bldg){RECORD_DELIMITER}
("entity"{TUPLE_DELIMITER}bldg:Zone_West{TUPLE_DELIMITER}Zone{TUPLE_DELIMITER}West HVAC zone in the building, served by AHU_01{TUPLE_DELIMITER}bldg){RECORD_DELIMITER}
("entity"{TUPLE_DELIMITER}brick:Temperature_Sensor{TUPLE_DELIMITER}TemperatureSensor{TUPLE_DELIMITER}Brick schema class representing temperature sensors{TUPLE_DELIMITER}brick){RECORD_DELIMITER}
("entity"{TUPLE_DELIMITER}brick:AHU{TUPLE_DELIMITER}AHU{TUPLE_DELIMITER}Brick schema class for Air Handling Units{TUPLE_DELIMITER}brick){RECORD_DELIMITER}
("entity"{TUPLE_DELIMITER}brick:HVAC_Zone{TUPLE_DELIMITER}Zone{TUPLE_DELIMITER}Brick schema class for HVAC zones{TUPLE_DELIMITER}brick){RECORD_DELIMITER}
("relationship"{TUPLE_DELIMITER}bldg:TempSensor_R101{TUPLE_DELIMITER}brick:Temperature_Sensor{TUPLE_DELIMITER}rdf:type{TUPLE_DELIMITER}TempSensor_R101 is an instance of the Brick Temperature_Sensor class{TUPLE_DELIMITER}10){RECORD_DELIMITER}
("relationship"{TUPLE_DELIMITER}bldg:TempSensor_R101{TUPLE_DELIMITER}bldg:AHU_01{TUPLE_DELIMITER}brick:isPointOf{TUPLE_DELIMITER}The temperature sensor is a measurement point of AHU_01{TUPLE_DELIMITER}9){RECORD_DELIMITER}
("relationship"{TUPLE_DELIMITER}bldg:AHU_01{TUPLE_DELIMITER}brick:AHU{TUPLE_DELIMITER}rdf:type{TUPLE_DELIMITER}AHU_01 is an instance of the Brick AHU class{TUPLE_DELIMITER}10){RECORD_DELIMITER}
("relationship"{TUPLE_DELIMITER}bldg:AHU_01{TUPLE_DELIMITER}bldg:Zone_West{TUPLE_DELIMITER}brick:feeds{TUPLE_DELIMITER}AHU_01 supplies conditioned air to the West zone{TUPLE_DELIMITER}9){RECORD_DELIMITER}
("relationship"{TUPLE_DELIMITER}bldg:Zone_West{TUPLE_DELIMITER}brick:HVAC_Zone{TUPLE_DELIMITER}rdf:type{TUPLE_DELIMITER}Zone_West is an instance of the Brick HVAC_Zone class{TUPLE_DELIMITER}10){COMPLETION_DELIMITER}

#############################

######################
entity_types: [{entity_types_str}]
text: {{input_text}}
######################
output:
"""

    return ChatPromptTemplate.from_template(prompt_template)


def create_sparql_generation_prompt() -> ChatPromptTemplate:
    """
    Create a prompt template for generating SPARQL queries from GraphRAG context
    
    Returns:
        ChatPromptTemplate for SPARQL query generation
    """
    
    prompt_template = """
-Goal-
Given a natural language query about a building and context from a GraphRAG knowledge graph (entities, relationships, communities), generate an accurate SPARQL query using the correct RDF prefixes and predicates.

-Context-
You have access to:
1. Entities: Building components with their types and prefixes (e.g., ex:TempSensor_R101, brick:Temperature_Sensor)
2. Relationships: RDF predicates connecting entities (e.g., brick:hasPoint, bot:containsZone, rdf:type)
3. Communities: Groups of related entities (e.g., HVAC systems, specific floors)
4. Prefixes: Available namespaces (brick:, bot:, saref:, ex:, rdf:, rdfs:)
5. External Timeseries References (if present): Entities linked via `ashrae:hasExternalReference` or `ref:hasExternalReference` to blank nodes containing `ref:hasTimeseriesId` and `ref:storedAt`.

-Steps-
1. Analyze the user query to identify:
   - What entities are being asked about (sensors, zones, equipment, etc.)
   - What properties or relationships are needed
   - What filters or conditions apply

2. Map query terms to ontology concepts:
   - "temperature sensors" → brick:Temperature_Sensor
   - "in the west zone" → ex:Zone_West with bot:containsZone
   - "readings" / "history" / "analysis" → retrieve external timeseries references.

3. Construct SPARQL query with:
   - PREFIX declarations for all used namespaces
   - SELECT clause with requested variables
   - WHERE clause with triple patterns from the graph
   - FILTER clauses for conditions
   - Optional ORDER BY, LIMIT as needed

    CRITICAL: EXTERNAL TIMESERIES REFERENCE EXTRACTION
    For ANY query involving sensors, setpoints, devices, or points (even if the user did not explicitly ask for IDs):
    - ALWAYS include an OPTIONAL block to retrieve external timeseries references (`?timeseriesId` and `?storedAt`).
    - Use `OPTIONAL` so that entities without references are still returned.
    - Pattern:
      OPTIONAL {{
        ?entity ashrae:hasExternalReference|ref:hasExternalReference ?ref .
        ?ref ref:hasTimeseriesId ?timeseriesId .
        ?ref ref:storedAt ?storedAt .
      }}
    - Add `?timeseriesId` and `?storedAt` to the SELECT clause.

4. Ensure prefixes match exactly those in the knowledge graph

5. Return only the complete SPARQL query, properly formatted

-Examples-
######################

Example 1:
Query: "What temperature sensors are in the west zone?"

Context entities: ex:TempSensor_R101, ex:Zone_West, brick:Temperature_Sensor
Context relationships: brick:isPointOf, brick:feeds, bot:containsZone
Available prefixes: brick:, bot:, ex:, rdf:, rdfs:, ashrae:, ref:

Output:
```sparql
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX bot: <https://w3id.org/bot#>
PREFIX ex: <http://example.org/building#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX ashrae: <https://data.ashrae.org/standard223#>
PREFIX ref: <https://brickschema.org/schema/Brick/ref#>

SELECT ?sensor ?zone ?timeseriesId ?storedAt
WHERE {{
  ?sensor rdf:type brick:Temperature_Sensor .
  ?zone rdf:type brick:HVAC_Zone .
  ?sensor brick:isPointOf ?equipment .
  ?equipment brick:feeds ?zone .
  FILTER(CONTAINS(STR(?zone), "West"))
  OPTIONAL {{
    ?sensor ashrae:hasExternalReference|ref:hasExternalReference ?ref .
    ?ref ref:hasTimeseriesId ?timeseriesId .
    ?ref ref:storedAt ?storedAt .
  }}
}}
```

#############################

Example 2:
Query: "List all equipment on the first floor"

Context entities: ex:Floor_01, ex:AHU_01, ex:VAV_101, bot:Storey
Context relationships: bot:hasStorey, bot:containsElement, rdf:type
Available prefixes: brick:, bot:, ex:, rdf:

Output:
```sparql
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX bot: <https://w3id.org/bot#>
PREFIX ex: <http://example.org/building#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

SELECT ?equipment ?equipmentType
WHERE {{
  ex:Floor_01 rdf:type bot:Storey .
  ex:Floor_01 bot:containsElement ?equipment .
  ?equipment rdf:type ?equipmentType .
  FILTER(STRSTARTS(STR(?equipmentType), STR(brick:Equipment)))
}}
```

Example 3:
Query: "What was the CO level in room 5.06 yesterday? (return IDs)"

Context entities: bldg:CO_Level_Sensor_5.06, brick:CO_Level_Sensor, brick:HVAC_Zone
Available prefixes: brick:, bot:, bldg:, ashrae:, ref:, rdf:, rdfs:

Output:
```sparql
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX ashrae: <https://data.ashrae.org/standard223#>
PREFIX ref: <https://brickschema.org/schema/Brick/ref#>
PREFIX bldg: <http://example.org/building#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

SELECT ?sensor ?timeseriesId ?storedAt
WHERE {{
    ?sensor rdf:type brick:CO_Level_Sensor .
    FILTER(STR(?sensor) = STR(bldg:CO_Level_Sensor_5.06))
    OPTIONAL {{
        ?sensor ashrae:hasExternalReference|ref:hasExternalReference ?ref .
        ?ref ref:hasTimeseriesId ?timeseriesId .
        ?ref ref:storedAt ?storedAt .
    }}
}}
```

#############################

-Real Query-
######################
User Query: {user_query}

GraphRAG Context:
{graphrag_context}

Available Prefixes:
{prefixes}

Generate SPARQL query:
######################
"""

    return ChatPromptTemplate.from_template(prompt_template)
