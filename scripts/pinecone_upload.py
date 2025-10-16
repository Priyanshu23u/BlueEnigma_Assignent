import json
import time
import os
import sys
import numpy as np
import logging
from tqdm import tqdm
from pinecone import Pinecone, ServerlessSpec
from transformers import AutoTokenizer, AutoModel
import torch

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('pinecone_upload.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import config

# -------------------------
# Load embedding model
# -------------------------
logger.info("Loading embedding model...")
tokenizer = AutoTokenizer.from_pretrained("jinaai/jina-embeddings-v2-base-en")
embedding_model = AutoModel.from_pretrained(
    "jinaai/jina-embeddings-v2-base-en", trust_remote_code=True
)
logger.info("Embedding model loaded successfully")

def get_embedding(text):
    """Generate embedding for text"""
    try:
        inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
        with torch.no_grad():
            embeddings = embedding_model(**inputs).pooler_output
        return embeddings[0].cpu().numpy()
    except Exception as e:
        logger.error(f"Error generating embedding: {e}")
        return None

def normalize_vector(vec):
    """Normalize vector to unit length"""
    if vec is None:
        return None
    norm = np.linalg.norm(vec)
    if norm == 0:
        return vec.tolist()
    return (vec / norm).tolist()

def upsert_with_retry(index, vectors, max_retries=3, retry_delay=2):
    """Upsert vectors with retry logic"""
    for attempt in range(max_retries):
        try:
            result = index.upsert(vectors)
            return result, None
        except Exception as e:
            if attempt < max_retries - 1:
                logger.warning(f"Upsert attempt {attempt + 1} failed: {e}. Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
            else:
                logger.error(f"Upsert failed after {max_retries} attempts: {e}")
                return None, e
    return None, Exception("Max retries exceeded")

# -------------------------
# Pinecone setup
# -------------------------
logger.info("Initializing Pinecone...")
pc = Pinecone(api_key=config.PINECONE_API_KEY)

# Check if index exists
existing_indexes = [idx.name for idx in pc.list_indexes()]
logger.info(f"Existing indexes: {existing_indexes}")

if config.PINECONE_INDEX_NAME not in existing_indexes:
    logger.info(f"Creating new index: {config.PINECONE_INDEX_NAME}")
    pc.create_index(
        name=config.PINECONE_INDEX_NAME,
        dimension=config.PINECONE_VECTOR_DIM,
        metric="cosine",
        spec=ServerlessSpec(
            cloud=config.PINECONE_CLOUD,
            region=config.PINECONE_REGION
        )
    )
    logger.info("Index created successfully")
    # Wait for index to be ready
    time.sleep(5)
else:
    logger.info(f"Using existing index: {config.PINECONE_INDEX_NAME}")

index = pc.Index(config.PINECONE_INDEX_NAME)

# -------------------------
# Load dataset
# -------------------------
DATA_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data', 'vietnam_travel_dataset.json'))
BATCH_SIZE = 32  # Optimized batch size

logger.info(f"Loading data from: {DATA_FILE}")
try:
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        nodes = json.load(f)
    logger.info(f"Loaded {len(nodes)} nodes from dataset")
except Exception as e:
    logger.error(f"Error loading dataset: {e}")
    sys.exit(1)

# -------------------------
# Prepare items for upload
# -------------------------
items = []
skipped = 0
seen_ids = set()

for node in nodes:
    # Get semantic text
    semantic_text = node.get("semantic_text") or (node.get("description") or "")[:1000]
    
    if not semantic_text.strip():
        skipped += 1
        continue
    
    node_id = str(node["id"])
    
    # Check for duplicate IDs
    if node_id in seen_ids:
        logger.warning(f"Duplicate ID found: {node_id}. Skipping...")
        skipped += 1
        continue
    
    seen_ids.add(node_id)
    
    # Prepare metadata
    meta = {
        "id": node.get("id"),
        "type": node.get("type"),
        "name": node.get("name"),
        "city": node.get("city", node.get("region", "")),
        "tags": node.get("tags", [])
    }
    items.append((node_id, semantic_text, meta))

logger.info(f"Prepared {len(items)} items for upload (skipped {skipped} invalid items)")

# -------------------------
# Upload embeddings with improvements
# -------------------------
print(f"\n{'='*60}")
print(f"Preparing to upsert {len(items)} items to Pinecone...")
print(f"{'='*60}\n")

successful_upserts = 0
failed_upserts = 0
total_batches = (len(items) + BATCH_SIZE - 1) // BATCH_SIZE

for i in tqdm(range(0, len(items), BATCH_SIZE), desc="Uploading batches", unit="batch"):
    batch = items[i:i+BATCH_SIZE]
    batch_num = i // BATCH_SIZE + 1
    
    try:
        # Extract batch data
        ids = [item[0] for item in batch]
        texts = [item[1] for item in batch]
        metas = [item[2] for item in batch]
        
        # Generate and normalize embeddings
        embeddings = []
        valid_items = []
        
        for idx, text in enumerate(texts):
            emb = get_embedding(text)
            if emb is not None:
                normalized_emb = normalize_vector(emb)
                if normalized_emb is not None:
                    embeddings.append(normalized_emb)
                    valid_items.append((ids[idx], metas[idx]))
        
        if not embeddings:
            logger.warning(f"Batch {batch_num}/{total_batches}: No valid embeddings generated")
            failed_upserts += len(batch)
            continue
        
        # Prepare vectors for upsert
        vectors = [
            {"id": item[0], "values": emb, "metadata": item[1]} 
            for emb, item in zip(embeddings, valid_items)
        ]
        
        # Upsert with retry logic
        result, error = upsert_with_retry(index, vectors)
        
        if result:
            successful_upserts += len(vectors)
            logger.debug(f"Batch {batch_num}/{total_batches}: Successfully upserted {len(vectors)} vectors")
        else:
            failed_upserts += len(vectors)
            logger.error(f"Batch {batch_num}/{total_batches}: Failed to upsert batch")
        
        # Rate limiting - small delay between batches
        time.sleep(0.1)
        
    except Exception as e:
        logger.error(f"Unexpected error in batch {batch_num}/{total_batches}: {e}")
        failed_upserts += len(batch)

# -------------------------
# Final statistics
# -------------------------
print(f"\n{'='*60}")
print(f"Upload Complete!")
print(f"{'='*60}")
print(f"✓ Successful upserts: {successful_upserts}")
print(f"✗ Failed upserts: {failed_upserts}")
print(f"Total processed: {successful_upserts + failed_upserts}")
print(f"{'='*60}\n")

# Get index statistics
try:
    stats = index.describe_index_stats()
    logger.info(f"Index statistics: {stats}")
    print(f"Index now contains {stats.get('total_vector_count', 'unknown')} vectors")
except Exception as e:
    logger.error(f"Error retrieving index stats: {e}")

logger.info("Upload process completed")
