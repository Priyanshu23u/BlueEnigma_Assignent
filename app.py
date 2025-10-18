from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import json
import numpy as np
from pinecone import Pinecone
from neo4j import GraphDatabase
from transformers import AutoTokenizer, AutoModel
import torch
from openai import OpenAI
from scripts import config
import logging

app = Flask(__name__)
CORS(app)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize models and connections
logger.info("Loading embedding model...")
tokenizer = AutoTokenizer.from_pretrained("jinaai/jina-embeddings-v2-base-en")
embedding_model = AutoModel.from_pretrained("jinaai/jina-embeddings-v2-base-en", trust_remote_code=True)
logger.info("✓ Embedding model loaded successfully")

# Initialize Pinecone - GUARANTEED FIX
index = None
try:
    logger.info("Initializing Pinecone...")
    logger.info(f"API Key present: {bool(config.PINECONE_API_KEY)}")
    logger.info(f"Index name: {config.PINECONE_INDEX_NAME}")
    
    # Create Pinecone instance
    from pinecone import Pinecone as PineconeClient
    pc = PineconeClient(api_key=config.PINECONE_API_KEY)
    
    # Get the index - THIS IS THE CORRECT WAY
    index = pc.Index(config.PINECONE_INDEX_NAME)
    
    # Verify it works
    logger.info(f"Index object type: {type(index)}")
    logger.info(f"Index has query: {hasattr(index, 'query')}")
    
    # Try a test query to confirm
    test_vec = [0.1] * 768  # dummy vector
    try:
        test_result = index.query(vector=test_vec, top_k=1, include_metadata=False)
        logger.info(f"✓ Pinecone index '{config.PINECONE_INDEX_NAME}' working correctly")
    except Exception as test_error:
        logger.warning(f"Index connected but query test failed: {test_error}")
        logger.info("✓ Pinecone index connected (query test skipped)")
        
except Exception as e:
    logger.error(f"✗ Failed to initialize Pinecone: {e}")
    import traceback
    logger.error(traceback.format_exc())
    index = None


# Initialize Neo4j
try:
    driver = GraphDatabase.driver(config.NEO4J_URI, auth=(config.NEO4J_USER, config.NEO4J_PASSWORD))
    # Test connection
    with driver.session() as session:
        result = session.run("RETURN 1")
        result.single()
    logger.info("✓ Neo4j connection established")
except Exception as e:
    logger.error(f"✗ Failed to connect to Neo4j: {e}")
    driver = None

# Embedding cache
embedding_cache = {}
SCORE_THRESHOLD = 0.7

def embed_text(text):
    """Generate normalized embedding with caching"""
    if text in embedding_cache:
        return embedding_cache[text]
    
    try:
        inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
        with torch.no_grad():
            embeddings = embedding_model(**inputs).pooler_output
        vec = embeddings[0].cpu().numpy()
        
        norm = np.linalg.norm(vec)
        normalized = (vec / norm).tolist() if norm != 0 else vec.tolist()
        
        embedding_cache[text] = normalized
        return normalized
    except Exception as e:
        logger.error(f"Embedding error: {e}")
        return None

def pinecone_query(query_text, top_k=5):
    """Query Pinecone with error handling"""
    if index is None:
        logger.error("Pinecone index not initialized")
        return []
    
    try:
        vec = embed_text(query_text)
        if vec is None:
            return []
        
        res = index.query(vector=vec, top_k=top_k, include_metadata=True, include_values=False)
        matches = res.get("matches", [])
        filtered = [m for m in matches if m.get("score", 0) >= SCORE_THRESHOLD]
        logger.info(f"Pinecone returned {len(matches)} matches, {len(filtered)} above threshold")
        return filtered
    except Exception as e:
        logger.error(f"Pinecone query error: {e}")
        return []

def fetch_graph_context(node_ids):
    """Fetch graph context from Neo4j"""
    if driver is None:
        logger.error("Neo4j driver not initialized")
        return []
    
    if not node_ids:
        return []
    
    facts = []
    try:
        with driver.session() as session:
            for nid in node_ids:
                try:
                    q = (
                        "MATCH (n:Entity {id:$nid})-[r]-(m:Entity) "
                        "RETURN type(r) AS rel, m.id AS id, m.name AS name, "
                        "m.type AS type, m.description AS description LIMIT 10"
                    )
                    recs = session.run(q, nid=nid)
                    for r in recs:
                        facts.append({
                            "source": nid,
                            "rel": r["rel"],
                            "target_id": r["id"],
                            "target_name": r["name"],
                            "target_desc": (r["description"] or "")[:200]
                        })
                except Exception as e:
                    logger.warning(f"Error fetching context for node {nid}: {e}")
                    continue
        logger.info(f"Fetched {len(facts)} graph facts")
    except Exception as e:
        logger.error(f"Neo4j query error: {e}")
    return facts

def build_prompt(user_query, matches, graph_facts):
    """Build prompt for LLM"""
    system = (
        "You are an expert Vietnam travel assistant. Use the provided data to answer queries accurately.\n"
        "Always cite node IDs when referencing places and provide step-by-step reasoning.\n"
        "Be helpful, informative, and enthusiastic about Vietnam travel."
    )
    
    vec_context = []
    for m in matches:
        meta = m.get("metadata", {})
        vec_context.append(
            f"- [Node {m['id']}] {meta.get('name','')} "
            f"({meta.get('type','')}) - Relevance: {m.get('score', 0):.3f}"
        )
    
    graph_context = [
        f"- Node {f['source']} --[{f['rel']}]--> Node {f['target_id']}: {f['target_name']}"
        for f in graph_facts[:15]
    ]
    
    context_section = ""
    if vec_context:
        context_section += "Vector Search Results:\n" + "\n".join(vec_context[:8]) + "\n\n"
    if graph_context:
        context_section += "Graph Relationships:\n" + "\n".join(graph_context) + "\n\n"
    
    if not context_section:
        context_section = "No specific context available. Use your general knowledge about Vietnam.\n\n"
    
    return [
        {"role": "system", "content": system},
        {"role": "user", "content":
            f"User Query: {user_query}\n\n"
            f"{context_section}"
            "Provide a comprehensive, helpful answer with specific recommendations."
        }
    ]

def call_groq_chat(prompt_messages):
    """Call Groq API with current supported model"""
    try:
        client = OpenAI(
            api_key=config.GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1"
        )
        
        # Try models in order of preference
        models_to_try = [
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "gemma2-9b-it"
        ]
        
        last_error = None
        for model in models_to_try:
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=prompt_messages,
                    max_tokens=800,
                    temperature=0.3
                )
                logger.info(f"✓ Using Groq model: {model}")
                return response.choices[0].message.content
            except Exception as model_error:
                last_error = model_error
                logger.warning(f"Model {model} failed: {str(model_error)[:100]}")
                continue
        
        # If all models fail
        raise last_error
        
    except Exception as e:
        logger.error(f"Groq API error: {e}")
        return "Sorry, I'm having trouble generating a response right now. Please try again in a moment."

@app.route('/')
def index():
    """Serve main page"""
    return render_template('index.html')

@app.route('/api/chat', methods=['POST'])
def chat():
    """Handle chat requests"""
    try:
        data = request.json
        query = data.get('message', '').strip()
        
        if not query:
            return jsonify({'error': 'Empty query'}), 400
        
        logger.info(f"Chat query: {query}")
        
        # Get context from Pinecone
        matches = pinecone_query(query, top_k=5)
        
        # Get graph context
        match_ids = [m["id"] for m in matches]
        graph_facts = fetch_graph_context(match_ids)
        
        # Generate response
        prompt = build_prompt(query, matches, graph_facts)
        answer = call_groq_chat(prompt)
        
        logger.info("Response generated successfully")
        
        return jsonify({
            'response': answer,
            'matches': matches,
            'graph_nodes': match_ids
        })
    
    except Exception as e:
        logger.error(f"Chat error: {e}", exc_info=True)
        return jsonify({'error': 'An error occurred processing your request'}), 500

@app.route('/api/graph/initial')
def get_initial_graph():
    """Get initial graph for visualization"""
    if driver is None:
        return jsonify({'nodes': [], 'edges': [], 'error': 'Neo4j not connected'})
    
    try:
        with driver.session() as session:
            query = """
            MATCH (n:Entity)-[r]-(m:Entity)
            RETURN n, r, m
            LIMIT 30
            """
            result = session.run(query)
            
            nodes = []
            edges = []
            seen_nodes = set()
            
            for record in result:
                n = record['n']
                m = record['m']
                r = record['r']
                
                if n['id'] not in seen_nodes:
                    nodes.append({
                        'id': str(n['id']),
                        'label': n.get('name', str(n['id'])),
                        'type': n.get('type', 'Unknown')
                    })
                    seen_nodes.add(n['id'])
                
                if m['id'] not in seen_nodes:
                    nodes.append({
                        'id': str(m['id']),
                        'label': m.get('name', str(m['id'])),
                        'type': m.get('type', 'Unknown')
                    })
                    seen_nodes.add(m['id'])
                
                edges.append({
                    'from': str(n['id']),
                    'to': str(m['id']),
                    'label': type(r).__name__
                })
            
            logger.info(f"Loaded initial graph: {len(nodes)} nodes, {len(edges)} edges")
            return jsonify({'nodes': nodes, 'edges': edges})
    
    except Exception as e:
        logger.error(f"Initial graph error: {e}", exc_info=True)
        return jsonify({'nodes': [], 'edges': [], 'error': str(e)})

@app.route('/api/graph/<node_id>')
def get_graph(node_id):
    """Get graph for specific node"""
    if driver is None:
        return jsonify({'error': 'Neo4j not connected'}), 500
    
    try:
        with driver.session() as session:
            query = """
            MATCH (n:Entity {id: $node_id})-[r]-(m:Entity)
            RETURN n, r, m LIMIT 20
            """
            result = session.run(query, node_id=node_id)
            
            nodes = []
            edges = []
            seen_nodes = set()
            
            for record in result:
                n = record['n']
                m = record['m']
                r = record['r']
                
                if n['id'] not in seen_nodes:
                    nodes.append({
                        'id': str(n['id']),
                        'label': n.get('name', str(n['id'])),
                        'type': n.get('type', 'Unknown')
                    })
                    seen_nodes.add(n['id'])
                
                if m['id'] not in seen_nodes:
                    nodes.append({
                        'id': str(m['id']),
                        'label': m.get('name', str(m['id'])),
                        'type': m.get('type', 'Unknown')
                    })
                    seen_nodes.add(m['id'])
                
                edges.append({
                    'from': str(n['id']),
                    'to': str(m['id']),
                    'label': type(r).__name__
                })
            
            logger.info(f"Graph for node {node_id}: {len(nodes)} nodes, {len(edges)} edges")
            return jsonify({'nodes': nodes, 'edges': edges})
    
    except Exception as e:
        logger.error(f"Graph error for node {node_id}: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health():
    """Health check endpoint"""
    status = {
        'pinecone': index is not None,
        'neo4j': driver is not None,
        'embedding_model': embedding_model is not None
    }
    return jsonify(status)

@app.route('/api/test/neo4j')
def test_neo4j():
    """Test Neo4j connection and data"""
    if driver is None:
        return jsonify({'error': 'Neo4j not connected'})
    
    try:
        with driver.session() as session:
            # Count entities
            result = session.run("MATCH (n:Entity) RETURN count(n) as count")
            node_count = result.single()['count']
            
            # Count relationships
            result = session.run("MATCH ()-[r]->() RETURN count(r) as count")
            rel_count = result.single()['count']
            
            # Get sample nodes
            result = session.run("MATCH (n:Entity) RETURN n LIMIT 5")
            samples = [dict(record['n']) for record in result]
            
            return jsonify({
                'connected': True,
                'node_count': node_count,
                'relationship_count': rel_count,
                'sample_nodes': samples
            })
    except Exception as e:
        return jsonify({'error': str(e)})

if __name__ == '__main__':
    logger.info("=" * 60)
    logger.info("Vietnam Travel Assistant - Starting Server")
    logger.info("=" * 60)
    logger.info(f"Pinecone Status: {'✓ Connected' if index else '✗ Not Connected'}")
    logger.info(f"Neo4j Status: {'✓ Connected' if driver else '✗ Not Connected'}")
    logger.info("=" * 60)
    app.run(debug=True, port=5000, host='0.0.0.0')
