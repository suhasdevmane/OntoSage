"""
Create GraphDB Similarity Index
===============================
This script configures the GraphDB Similarity Plugin index for the RAG service.
It targets the "bldg" repository and creates a robust index for entity retrieval.
"""
import sys
sys.path.append("/app")

import asyncio
import httpx
import os
from shared.utils import get_logger

# Configure logger
logger = get_logger(__name__)

# Configuration
GRAPHDB_URL = os.getenv("GRAPHDB_URL", "http://localhost:7200")
REPOSITORY = os.getenv("GRAPHDB_REPOSITORY", "bldg")
INDEX_NAME = os.getenv("GRAPHDB_SIMILARITY_INDEX", "bldg_index")

async def create_index():
    """Create GraphDB Similarity Index using Connector API"""
    
    connector_endpoint = f"{GRAPHDB_URL}/rest/connectors"
    
    logger.info(f"🚀 Creating Similarity Index '{INDEX_NAME}' in repository '{REPOSITORY}'...")
    logger.info(f"📡 GraphDB URL: {GRAPHDB_URL}")
    
    # GraphDB Connector API Configuration
    # This is the correct way to create similarity indexes in GraphDB
    # NOTE: For Similarity Plugin, we need to use the Similarity Index configuration, NOT Lucene Connector directly.
    # However, the user mentioned they are using "similarity indexing from the graphdb".
    # If they mean the Similarity Plugin (which uses Lucene under the hood but has a different API),
    # we should use the Similarity API.
    # But the previous code was trying to create a Lucene Connector.
    # Let's try to create a Text Similarity Index using the Similarity Plugin API if possible,
    # or stick to the Lucene Connector if that's what was intended.
    # Given the user's context about "similarity indexing", let's assume they want the Similarity Plugin.
    
    # BUT, the user said "I have already created bldg_index and ready to use".
    # And our check showed NO existing Lucene connectors.
    # This implies the index might be a SIMILARITY index, not a generic Lucene connector.
    # Similarity indexes are managed via a different endpoint: /rest/similarity/indexes
    
    similarity_endpoint = f"{GRAPHDB_URL}/rest/similarity/indexes"
    
    # Let's just check if it exists first in this script, or try to create it if missing.
    # For now, let's update this script to use the Similarity API instead of Connector API.
    
    similarity_config = {
        "name": INDEX_NAME,
        "type": "text",
        "options": {
            "query": """
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX brick: <https://brickschema.org/schema/Brick#>

SELECT ?documentID ?documentText {
    ?documentID rdf:type ?type .
    FILTER(ISIRI(?documentID))
    
    # Get Label (optional)
    OPTIONAL { ?documentID rdfs:label ?label }
    
    # Get Type Name (strip namespace)
    BIND(REPLACE(STR(?type), "^.*[#/]([^#/]+)$", "$1") as ?typeName)
    
    # Get Entity Name (strip namespace)
    BIND(REPLACE(STR(?documentID), "^.*[#/]([^#/]+)$", "$1") as ?entityName)
    
    # Combine into a rich document text
    BIND(CONCAT(
        COALESCE(?label, ""), " ", 
        COALESCE(?typeName, ""), " ", 
        COALESCE(?entityName, "")
    ) as ?documentText)
}
""",
            "searchQuery": "",
            "stopWords": "a,an,the,and,or,of,to,in",
            "analyzer": "org.apache.lucene.analysis.en.EnglishAnalyzer"
        }
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            logger.info("📡 Creating Similarity Index via REST API...")
            
            # Create the index
            response = await client.post(
                similarity_endpoint,
                params={"name": INDEX_NAME}, # Some versions take name in query param
                json=similarity_config,
                headers={"X-GraphDB-Repository": REPOSITORY, "Content-Type": "application/json"}
            )
            
            if response.status_code in [200, 201]:
                logger.info(f"✅ Similarity Index '{INDEX_NAME}' created successfully!")
            elif response.status_code == 409 or "already exists" in response.text:
                logger.warning(f"⚠️ Similarity Index '{INDEX_NAME}' already exists.")
                # Rebuild
                logger.info("Attempting to rebuild...")
                rebuild_resp = await client.post(
                    f"{similarity_endpoint}/{INDEX_NAME}/rebuild",
                    headers={"X-GraphDB-Repository": REPOSITORY}
                )
                if rebuild_resp.status_code in [200, 202, 204]:
                     logger.info(f"✅ Index '{INDEX_NAME}' rebuild initiated.")
                else:
                     logger.error(f"❌ Failed to rebuild. Status: {rebuild_resp.status_code}")
            else:
                logger.error(f"❌ Failed to create index. Status: {response.status_code}")
                logger.error(f"Response: {response.text}")
                
    except Exception as e:
        logger.error(f"❌ Error creating index: {e}")

if __name__ == "__main__":
    asyncio.run(create_index())
