"""
GraphDB Ontology Importer
=========================
Automatically imports .ttl files from /app/input into the GraphDB repository.
This allows for easy deployment of new building ontologies by simply placing
the .ttl file in the input directory.
"""
import os
import glob
import httpx
import logging
import asyncio

logger = logging.getLogger(__name__)

# Configuration
GRAPHDB_URL = os.getenv("GRAPHDB_URL", "http://graphdb:7200")
REPOSITORY = os.getenv("GRAPHDB_REPOSITORY", "bldg")
INPUT_DIR = "/app/input"

async def import_ontology(retries=5, delay=5):
    """
    Scans /app/input for .ttl files and imports them into GraphDB.
    """
    logger.info(f"🔍 Scanning {INPUT_DIR} for ontology files...")
    
    if not os.path.exists(INPUT_DIR):
        logger.warning(f"⚠️ Input directory {INPUT_DIR} does not exist.")
        return

    ttl_files = glob.glob(os.path.join(INPUT_DIR, "*.ttl"))
    
    if not ttl_files:
        logger.warning(f"⚠️ No .ttl files found in {INPUT_DIR}.")
        # Fallback to checking if the repo is empty or has data?
        # For now, we assume the user might want to use the baked-in image data if no input is provided.
        return

    logger.info(f"📂 Found {len(ttl_files)} ontology files: {[os.path.basename(f) for f in ttl_files]}")
    
    # Endpoint for uploading statements
    # Header Content-Type: text/turtle
    url = f"{GRAPHDB_URL}/repositories/{REPOSITORY}/statements"
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        # Wait for GraphDB to be ready
        for i in range(retries):
            try:
                health = await client.get(f"{GRAPHDB_URL}/rest/repositories")
                if health.status_code == 200:
                    break
            except Exception:
                pass
            logger.info(f"⏳ Waiting for GraphDB ({i+1}/{retries})...")
            await asyncio.sleep(delay)
            
        for file_path in ttl_files:
            filename = os.path.basename(file_path)
            logger.info(f"🚀 Importing {filename}...")
            
            try:
                # We use specific context graph to allow easy clearing later if needed
                # context = f"http://ontosage.com/graph/{filename}"
                
                with open(file_path, "rb") as f:
                    content = f.read()
                    
                response = await client.post(
                    url,
                    content=content,
                    headers={
                        "Content-Type": "text/turtle",
                        # "X-GraphDB-Context": context # Optional: import into named graph
                    }
                )
                
                if response.status_code == 204:
                    logger.info(f"✅ Successfully imported {filename}")
                else:
                    logger.error(f"❌ Failed to import {filename}: {response.status_code} - {response.text}")
                    
            except Exception as e:
                logger.error(f"❌ Error importing {filename}: {e}")

    logger.info("✨ Ontology import process completed.")

if __name__ == "__main__":
    # Test run
    logging.basicConfig(level=logging.INFO)
    asyncio.run(import_ontology())
