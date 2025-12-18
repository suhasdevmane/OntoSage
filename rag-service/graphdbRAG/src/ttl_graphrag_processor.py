"""
TTL to GraphRAG Processing Pipeline
Processes Turtle ontology files through GraphRAG entity extraction
"""
import sys
from pathlib import Path
from typing import List, Dict, Optional
import subprocess
from langchain_text_splitters import TokenTextSplitter
from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI
import logging

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent))

from ttl_parser import TTLParser
from ontology_prompts import create_ontology_entity_extraction_prompt, create_sparql_generation_prompt

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TTLGraphRAGProcessor:
    """
    Processes TTL ontology files for GraphRAG indexing
    """
    
    def __init__(
        self,
        ttl_file_path: str,
        graphrag_root: str = "./",
        openai_model: str = "o3-mini",
        temperature: float = 0.0,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None
    ):
        """
        Initialize processor
        
        Args:
            ttl_file_path: Path to TTL ontology file
            graphrag_root: Root directory for GraphRAG workspace
            openai_model: OpenAI model to use for extraction
            temperature: LLM temperature (0.0 for deterministic)
            api_key: API key (optional, defaults to env vars)
            base_url: Base URL for API (optional, e.g. for Perplexity)
        """
        self.ttl_file_path = Path(ttl_file_path)
        self.graphrag_root = Path(graphrag_root)
        self.input_dir = self.graphrag_root / "inputs"
        self.output_dir = self.graphrag_root / "outputs"
        
        # Initialize LLM
        llm_kwargs = {
            "temperature": temperature,
            "model": openai_model
        }
        
        if api_key:
            llm_kwargs["api_key"] = api_key
        if base_url:
            llm_kwargs["base_url"] = base_url
            
        self.llm = ChatOpenAI(**llm_kwargs)
        
        # Initialize parser
        self.parser = TTLParser(str(self.ttl_file_path))
        
        # Storage
        self.entity_types: List[str] = []
        self.prefixes: Dict[str, str] = {}
        self.text_chunks: List[str] = []
        self.chunk_metadata: Dict[str, int] = {}
        
    def process_ttl(self) -> Dict:
        """
        Step 1: Parse TTL file and extract triples
        
        Returns:
            Dictionary with parsing results
        """
        logger.info(f"📖 Parsing TTL file: {self.ttl_file_path}")
        
        result = self.parser.parse()
        
        self.prefixes = self.parser.prefixes
        self.entity_types = self.parser.get_entity_types_from_ontology()
        
        logger.info(f"✅ Parsed {result['triple_count']} triples")
        logger.info(f"   Found {len(self.entity_types)} entity types")
        logger.info(f"   Found {len(self.prefixes)} prefixes")
        
        return result
    
    def chunk_triples(
        self,
        chunk_size: int = 10000,
        chunk_overlap: int = 1000,
        max_chunks: int = 140,
        auto_adjust: bool = True
    ) -> List[str]:
        """
        Step 2: Convert triples to text chunks for LLM processing
        
        Args:
            chunk_size: Target token count per chunk
            chunk_overlap: Token overlap between chunks
            max_chunks: Maximum allowed number of chunks
            auto_adjust: Whether to auto-increase chunk_size to honor max_chunks
        
        Returns:
            List of text chunks
        """
        logger.info(
            f"📝 Creating text chunks (size={chunk_size}, overlap={chunk_overlap}, max_chunks={max_chunks})"
        )
        
        # Get triples as text
        triples_text = "\n".join([
            f"{triple.subject} {triple.predicate} {triple.object} ."
            for triple in self.parser.triples
        ])
        
        # Add prefix context at the beginning
        prefix_context = "RDF Prefixes:\n" + self.parser.get_prefixes_as_sparql() + "\n\n"
        prefix_context += "RDF Triples:\n"
        
        full_text = prefix_context + triples_text
        
        # Split into chunks
        adjusted_chunk_size = chunk_size
        adjusted_overlap = chunk_overlap
        text_splitter = TokenTextSplitter(
            chunk_size=adjusted_chunk_size,
            chunk_overlap=adjusted_overlap,
            encoding_name="cl100k_base"
        )

        self.text_chunks = text_splitter.split_text(full_text)

        if auto_adjust:
            attempt = 0
            while len(self.text_chunks) > max_chunks and attempt < 6:
                attempt += 1
                adjusted_chunk_size = int(adjusted_chunk_size * 1.2)
                adjusted_overlap = min(int(adjusted_chunk_size * 0.1), adjusted_overlap)
                logger.info(
                    f"   🔁 Adjusting chunk plan (attempt {attempt}): size={adjusted_chunk_size}, overlap={adjusted_overlap}"
                )
                text_splitter = TokenTextSplitter(
                    chunk_size=adjusted_chunk_size,
                    chunk_overlap=adjusted_overlap,
                    encoding_name="cl100k_base"
                )
                self.text_chunks = text_splitter.split_text(full_text)

        chunk_count = len(self.text_chunks)
        logger.info(f"✅ Created {chunk_count} text chunks")

        if chunk_count > max_chunks:
            logger.error(
                f"❌ Chunk count {chunk_count} exceeds limit of {max_chunks}. Increase chunk_size or reduce data."
            )
            raise ValueError(
                f"Chunk count {chunk_count} exceeds max_chunks {max_chunks}. Adjust chunk size or filter TTL file."
            )

        if chunk_count > max_chunks * 0.9:
            logger.warning(
                f"⚠️  Chunk count {chunk_count} is close to the maximum budget ({max_chunks}). Processing may be slow."
            )

        self.chunk_metadata = {
            "chunk_size": adjusted_chunk_size,
            "chunk_overlap": adjusted_overlap,
            "chunk_count": chunk_count,
            "max_chunks": max_chunks
        }

        return self.text_chunks
    
    def extract_entities_and_relationships(
        self,
        chunk_indices: Optional[List[int]] = None,
        save_to_file: bool = True
    ) -> List[str]:
        """
        Step 3: Extract entities and relationships using LLM
        
        Args:
            chunk_indices: Specific chunk indices to process (None = all)
            save_to_file: Whether to save extractions to file
        
        Returns:
            List of extraction results (one per chunk)
        """
        logger.info(f"🤖 Extracting entities and relationships with {self.llm.model_name}")
        
        # Create prompt
        prompt_template = create_ontology_entity_extraction_prompt(self.entity_types)
        chain = prompt_template | self.llm | StrOutputParser()
        
        # Process chunks
        chunks_to_process = chunk_indices if chunk_indices else range(len(self.text_chunks))
        extractions = []
        
        for i in chunks_to_process:
            logger.info(f"   Processing chunk {i+1}/{len(self.text_chunks)}")
            
            try:
                extraction = chain.invoke({"input_text": self.text_chunks[i]})
                extractions.append(extraction)
                
                if save_to_file:
                    output_file = self.input_dir / f"extraction_chunk_{i:03d}.txt"
                    output_file.parent.mkdir(parents=True, exist_ok=True)
                    with open(output_file, 'w', encoding='utf-8') as f:
                        f.write(extraction)
                
            except Exception as e:
                logger.error(f"❌ Failed to process chunk {i}: {e}")
                extractions.append(f"ERROR: {str(e)}")
        
        logger.info(f"✅ Completed {len(extractions)} extractions")
        
        return extractions
    
    def prepare_graphrag_input(self) -> Path:
        """
        Step 4: Prepare input file for GraphRAG CLI
        Combines extracted entities/relationships into single input file
        
        Returns:
            Path to prepared input file
        """
        logger.info("📄 Preparing GraphRAG input file")
        
        self.input_dir.mkdir(parents=True, exist_ok=True)
        
        # Combine all extraction files
        extraction_files = sorted(self.input_dir.glob("extraction_chunk_*.txt"))
        
        if not extraction_files:
            logger.warning("⚠️  No extraction files found. Run extract_entities_and_relationships() first.")
            # Fallback: use chunked triples directly
            input_file = self.input_dir / "ontology_triples.txt"
            with open(input_file, 'w', encoding='utf-8') as f:
                f.write("\n\n".join(self.text_chunks))
            return input_file
        
        # Combine extractions
        combined_file = self.input_dir / "ontology_extractions.txt"
        
        with open(combined_file, 'w', encoding='utf-8') as outfile:
            # Add prefix information
            outfile.write("# RDF Ontology Knowledge Graph\n\n")
            outfile.write("## Prefixes\n")
            outfile.write(self.parser.get_prefixes_as_sparql())
            outfile.write("\n\n## Entity Types\n")
            outfile.write(", ".join(self.entity_types))
            outfile.write("\n\n## Extracted Entities and Relationships\n\n")
            
            for extraction_file in extraction_files:
                with open(extraction_file, 'r', encoding='utf-8') as infile:
                    outfile.write(infile.read())
                    outfile.write("\n\n---\n\n")
        
        logger.info(f"✅ Created GraphRAG input: {combined_file}")
        
        return combined_file
    
    def run_graphrag_indexing(self, timeout: Optional[int] = 1800) -> subprocess.CompletedProcess:
        """
        Step 5: Run GraphRAG CLI indexing
        
        Args:
            timeout: Timeout in seconds (default: 30 minutes)
        
        Returns:
            subprocess.CompletedProcess result
        """
        logger.info("🚀 Running GraphRAG indexing (this may take 10-20 minutes)")
        
        command = [
            'graphrag', 'index',
            '--root', str(self.graphrag_root),
            '--verbose'
        ]
        
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(self.graphrag_root)
            )
            
            if result.returncode == 0:
                logger.info("✅ GraphRAG indexing completed successfully")
            else:
                logger.error(f"❌ GraphRAG indexing failed: {result.stderr}")
            
            return result
            
        except subprocess.TimeoutExpired:
            logger.error(f"❌ GraphRAG indexing timed out after {timeout} seconds")
            raise
    
    def query_graphrag(
        self,
        query: str,
        method: str = "local",
        community_level: int = 2,
        dynamic_community_selection: bool = False
    ) -> str:
        """
        Query the GraphRAG knowledge graph
        
        Args:
            query: Natural language query
            method: "local", "global", or "drift"
            community_level: Community hierarchy level (0-N)
            dynamic_community_selection: Use dynamic selection for global search
        
        Returns:
            Query result as string
        """
        logger.info(f"🔍 Querying GraphRAG ({method}): {query}")
        
        command = [
            'graphrag', 'query',
            '--root', str(self.graphrag_root),
            '--method', method,
            '--query', query,
            '--community-level', str(community_level)
        ]
        
        if dynamic_community_selection:
            command.append('--dynamic-community-selection')
        
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(self.graphrag_root)
            )
            
            result.check_returncode()
            
            return result.stdout.strip()
            
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Query failed: {e.stderr}")
            raise
    
    def generate_sparql_from_query(
        self,
        user_query: str,
        graphrag_method: str = "local"
    ) -> str:
        """
        Generate SPARQL query using GraphRAG context
        
        Args:
            user_query: Natural language query
            graphrag_method: GraphRAG search method for context
        
        Returns:
            Generated SPARQL query
        """
        logger.info(f"🔧 Generating SPARQL for: {user_query}")
        
        # Get GraphRAG context
        graphrag_context = self.query_graphrag(user_query, method=graphrag_method)
        
        # Create SPARQL generation prompt
        sparql_prompt = create_sparql_generation_prompt()
        chain = sparql_prompt | self.llm | StrOutputParser()
        
        # Generate SPARQL
        sparql_query = chain.invoke({
            "user_query": user_query,
            "graphrag_context": graphrag_context,
            "prefixes": self.parser.get_prefixes_as_sparql()
        })
        
        logger.info("✅ Generated SPARQL query")
        
        return sparql_query
    
    def run_full_pipeline(
        self,
        chunk_size: int = 10000,
        chunk_overlap: int = 1000,
        max_chunks: int = 140,
        test_mode: bool = False,
        test_mode_chunk_index: int = 10
    ) -> Dict:
        """
        Run complete TTL → GraphRAG pipeline
        
        Args:
            chunk_size: Token size target for chunking
            chunk_overlap: Token overlap between adjacent chunks
            max_chunks: Hard budget for chunk count
            test_mode: When True, only process the configured chunk index
            test_mode_chunk_index: Chunk index to run when test_mode=True
        
        Returns:
            Dictionary with pipeline results
        """
        logger.info("🚀 Starting full TTL → GraphRAG pipeline")
        
        results = {}
        
        # Step 1: Parse TTL
        results['parse'] = self.process_ttl()
        
        # Step 2: Chunk triples
        self.chunk_triples(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            max_chunks=max_chunks
        )
        results['chunks'] = len(self.text_chunks)
        results['chunk_plan'] = self.chunk_metadata
        
        # Step 3: Extract entities
        chunk_indices = None
        
        if test_mode:
            valid_index = min(test_mode_chunk_index, len(self.text_chunks) - 1)
            if valid_index < 0:
                raise ValueError("No chunks generated. Cannot run in test mode.")
            chunk_indices = [valid_index]
            logger.info(f"🧪 TEST MODE: Processing ONLY chunk #{valid_index}")
        
        extractions = self.extract_entities_and_relationships(chunk_indices=chunk_indices)
        results['extractions'] = len(extractions)
        
        # Step 4: Prepare GraphRAG input
        input_file = self.prepare_graphrag_input()
        results['input_file'] = str(input_file)
        
        logger.info("✅ Pipeline preparation complete")
        logger.info("ℹ️  Next step: Run GraphRAG indexing with processor.run_graphrag_indexing()")
        
        return results


def main():
    """Example usage"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Process TTL files for GraphRAG")
    parser.add_argument("ttl_file", help="Path to TTL ontology file")
    parser.add_argument("--graphrag-root", default="./", help="GraphRAG workspace root")
    parser.add_argument("--model", default="o3-mini", help="LLM model to use")
    parser.add_argument("--chunk-size", type=int, default=10000, help="Chunk size in tokens")
    parser.add_argument("--chunk-overlap", type=int, default=1000, help="Chunk overlap in tokens")
    parser.add_argument("--max-chunks", type=int, default=140, help="Maximum allowed chunk count")
    parser.add_argument("--test-mode", action="store_true", help="Process only the configured test chunk (default index 10)")
    parser.add_argument("--test-chunk-index", type=int, default=10, help="Chunk index to run in test mode")
    
    args = parser.parse_args()
    
    # Initialize processor
    processor = TTLGraphRAGProcessor(
        ttl_file_path=args.ttl_file,
        graphrag_root=args.graphrag_root,
        openai_model=args.model
    )
    
    # Run pipeline
    results = processor.run_full_pipeline(
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        max_chunks=args.max_chunks,
        test_mode=args.test_mode,
        test_mode_chunk_index=args.test_chunk_index
    )
    
    print("\n" + "="*60)
    print("📊 Pipeline Results:")
    print(f"   - Triples parsed: {results['parse']['triple_count']}")
    print(f"   - Text chunks: {results['chunks']}")
    if 'chunk_plan' in results:
        plan = results['chunk_plan']
        print(
            f"   - Chunk plan: size={plan['chunk_size']} | overlap={plan['chunk_overlap']} | chunks={plan['chunk_count']}/{plan['max_chunks']}"
        )
    print(f"   - Extractions: {results['extractions']}")
    print(f"   - Input file: {results['input_file']}")
    print("="*60)
    print("\n✅ Ready for GraphRAG indexing!")
    print(f"   Run: graphrag index --root {args.graphrag_root}")


if __name__ == "__main__":
    main()
