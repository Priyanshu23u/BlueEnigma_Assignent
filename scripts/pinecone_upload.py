import json
import time
import os
from tqdm import tqdm
from pinecone import Pinecone, ServerlessSpec
from transformers import AutoTokenizer, AutoModel
import torch
import config
import sys
import numpy as np

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# -------------------------
# Load embedding model
# -------------------------
tokenizer = AutoTokenizer.from_pretrained("jinaai/jina-embeddings-v2-base-en")
embedding_model = AutoModel.from_pretrained(
    "jinaai/jina-embeddings-v2-base-en", trust_remote_code=True
)

def get_embedding(text):
    inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
    with torch.no_grad():
        embeddings = embedding_model(**inputs).pooler_output
    return embeddings[0].cpu().numpy()

def normalize_vector(vec):
    norm = np.linalg.norm(vec)
    if norm == 0:
        return vec.tolist()
    return (vec / norm).tolist()

# -------------------------
# Pinecone setup
# -------------------------
pc = Pinecone(api_key=config.PINECONE_API_KEY)

if config.PINECONE_INDEX_NAME not in [idx.name for idx in pc.list_indexes()]:
    pc.create_index(
        name=config.PINECONE_INDEX_NAME,
        dimension=config.PINECONE_VECTOR_DIM,
        metric="cosine",
        spec=ServerlessSpec(
            cloud=config.PINECONE_CLOUD,
            region=config.PINECONE_REGION
        )
    )

index = pc.Index(config.PINECONE_INDEX_NAME)

# -------------------------
# Load dataset
# -------------------------
DATA_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data', 'vietnam_travel_dataset.json'))
BATCH_SIZE = 32

with open(DATA_FILE, "r", encoding="utf-8") as f:
    nodes = json.load(f)

items = []
for node in nodes:
    semantic_text = node.get("semantic_text") or (node.get("description") or "")[:1000]
    if not semantic_text.strip():
        continue
    meta = {
        "id": node.get("id"),
        "type": node.get("type"),
        "name": node.get("name"),
        "city": node.get("city", node.get("region", "")),
        "tags": node.get("tags", [])
    }
    items.append((str(node["id"]), semantic_text, meta))  # Pinecone IDs must be strings

# -------------------------
# Upload embeddings
# -------------------------
print(f"Preparing to upsert {len(items)} items to Pinecone...")

for i in tqdm(range(0, len(items), BATCH_SIZE), desc="Uploading batches"):
    batch = items[i:i+BATCH_SIZE]
    ids = [item[0] for item in batch]
    texts = [item[1] for item in batch]
    metas = [item[2] for item in batch]
    embeddings = [normalize_vector(get_embedding(text)) for text in texts]

    vectors = [{"id": _id, "values": emb, "metadata": meta} for _id, emb, meta in zip(ids, embeddings, metas)]
    index.upsert(vectors)
    time.sleep(0.2)

print("All items uploaded successfully.")
