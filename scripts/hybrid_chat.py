import json
import numpy as np
import logging
from pinecone import Pinecone
from neo4j import GraphDatabase
from transformers import AutoTokenizer, AutoModel
import torch
from openai import OpenAI
import config

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('chat_logs.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Embedding model
tokenizer = AutoTokenizer.from_pretrained("jinaai/jina-embeddings-v2-base-en")
embedding_model = AutoModel.from_pretrained("jinaai/jina-embeddings-v2-base-en", trust_remote_code=True)

# Embedding cache
embedding_cache = {}
CACHE_MAX_SIZE = 1000

def embed_text(text):
    """Generate normalized embedding with caching"""
    # Check cache first
    if text in embedding_cache:
        logger.info(f"Cache hit for query: {text[:50]}...")
        return embedding_cache[text]
    
    inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
    with torch.no_grad():
        embeddings = embedding_model(**inputs).pooler_output
    vec = embeddings[0].cpu().numpy()
    
    # Normalize vector
    norm = np.linalg.norm(vec)
    if norm == 0:
        normalized = vec.tolist()
    else:
        normalized = (vec / norm).tolist()
    
    # Store in cache with size limit
    if len(embedding_cache) >= CACHE_MAX_SIZE:
        # Remove oldest entry
        embedding_cache.pop(next(iter(embedding_cache)))
    embedding_cache[text] = normalized
    
    logger.info(f"Generated embedding for: {text[:50]}...")
    return normalized

# Initialize connections
pc = Pinecone(api_key=config.PINECONE_API_KEY)
index = pc.Index(config.PINECONE_INDEX_NAME)
driver = GraphDatabase.driver(config.NEO4J_URI, auth=(config.NEO4J_USER, config.NEO4J_PASSWORD))

# Configuration
SCORE_THRESHOLD = 0.7  # Only use high-quality matches

def pinecone_query(query_text, top_k=5):
    """Query Pinecone with error handling and score filtering"""
    try:
        vec = embed_text(query_text)
        res = index.query(vector=vec, top_k=top_k, include_metadata=True, include_values=False)
        matches = res.get("matches", [])
        
        # Filter by score threshold
        filtered_matches = [m for m in matches if m.get("score", 0) >= SCORE_THRESHOLD]
        logger.info(f"Pinecone returned {len(matches)} matches, {len(filtered_matches)} above threshold")
        
        return filtered_matches
    except Exception as e:
        logger.error(f"Pinecone query error: {e}")
        return []

def fetch_graph_context(node_ids, neighborhood_depth=1):
    """Fetch graph context with error handling"""
    facts = []
    try:
        with driver.session() as session:
            for nid in node_ids:
                try:
                    q = (
                        "MATCH (n:Entity {id:$nid})-[r]-(m:Entity) "
                        "RETURN type(r) AS rel, labels(m) AS labels, m.id AS id, "
                        "m.name AS name, m.type AS type, m.description AS description "
                        "LIMIT 10"
                    )
                    recs = session.run(q, nid=nid)
                    for r in recs:
                        facts.append({
                            "source": nid,
                            "rel": r["rel"],
                            "target_id": r["id"],
                            "target_name": r["name"],
                            "target_desc": (r["description"] or "")[:400],
                            "labels": r["labels"]
                        })
                except Exception as e:
                    logger.warning(f"Error fetching context for node {nid}: {e}")
                    continue
        logger.info(f"Fetched {len(facts)} graph facts")
    except Exception as e:
        logger.error(f"Neo4j connection error: {e}")
    
    return facts

def build_prompt(user_query, pinecone_matches, graph_facts):
    """Build enhanced prompt with chain-of-thought instructions"""
    system = (
        "You are an expert Vietnam travel assistant with deep knowledge of Vietnamese culture, geography, and tourism. "
        "Use the provided semantic search results and graph relationships to answer queries accurately and helpfully.\n\n"
        "Instructions:\n"
        "1. Always cite node IDs (in format 'node_XXX') when referencing specific places\n"
        "2. Provide step-by-step reasoning for itinerary suggestions\n"
        "3. Prioritize higher-scored results from the vector database\n"
        "4. If information is uncertain or incomplete, acknowledge this clearly\n"
        "5. Structure multi-day itineraries with clear daily breakdowns\n"
        "6. Consider practical travel logistics (distances, timing, etc.)"
    )
    
    vec_context = []
    for m in pinecone_matches:
        meta = m["metadata"]
        score = m.get("score", 0)
        snippet = f"- [Node {m['id']}] {meta.get('name','')} ({meta.get('type','')}) - Score: {score:.3f}"
        if meta.get("city"):
            snippet += f" | City: {meta.get('city')}"
        vec_context.append(snippet)
    
    graph_context = [
        f"- Node {f['source']} --[{f['rel']}]--> Node {f['target_id']}: {f['target_name']} - {f['target_desc'][:100]}..."
        for f in graph_facts[:20]
    ]
    
    prompt = [
        {"role": "system", "content": system},
        {"role": "user", "content":
            f"User Query: {user_query}\n\n"
            "=== Semantic Search Results (Vector DB) ===\n" + "\n".join(vec_context[:10]) + "\n\n"
            "=== Graph Relationships (Knowledge Graph) ===\n" + "\n".join(graph_context) + "\n\n"
            "Based on the above information, provide a comprehensive answer. "
            "Include specific node IDs and explain your reasoning step-by-step."
        }
    ]
    return prompt

def call_groq_chat(prompt_messages):
    """Call Groq API with error handling"""
    try:
        client = OpenAI(
            api_key=config.GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1"
        )
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=prompt_messages,
            max_tokens=800,
            temperature=0.3
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Groq API error: {e}")
        return "I apologize, but I'm having trouble generating a response right now. Please try again."

def interactive_chat():
    """Interactive chat with improved error handling and logging"""
    print("=" * 60)
    print("Vietnam Travel Assistant (Hybrid RAG)")
    print("Type 'exit' to quit, 'clear' to clear cache")
    print("=" * 60)
    
    while True:
        try:
            query = input("\n🌏 Your question: ").strip()
            
            if not query or query.lower() in ("exit", "quit"):
                print("Goodbye! Safe travels! 🛫")
                break
            
            if query.lower() == "clear":
                embedding_cache.clear()
                print("✓ Cache cleared")
                continue
            
            logger.info(f"User query: {query}")
            
            # Retrieve context
            matches = pinecone_query(query, top_k=5)
            
            if not matches:
                print("\n⚠️ No relevant results found. Try rephrasing your question.")
                continue
            
            match_ids = [m["id"] for m in matches]
            graph_facts = fetch_graph_context(match_ids)
            
            # Generate response
            prompt = build_prompt(query, matches, graph_facts)
            answer = call_groq_chat(prompt)
            
            print("\n" + "=" * 60)
            print("🤖 Assistant Answer:")
            print("=" * 60)
            print(answer)
            print("=" * 60)
            
            logger.info(f"Response generated successfully")
            
        except KeyboardInterrupt:
            print("\n\nGoodbye! Safe travels! 🛫")
            break
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            print("\n⚠️ An error occurred. Please try again.")

if __name__ == "__main__":
    interactive_chat()
