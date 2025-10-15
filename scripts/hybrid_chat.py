import json
import numpy as np
from pinecone import Pinecone
from neo4j import GraphDatabase
from transformers import AutoTokenizer, AutoModel
import torch
import requests
import config

# Embedding model
tokenizer = AutoTokenizer.from_pretrained("jinaai/jina-embeddings-v2-base-en")
embedding_model = AutoModel.from_pretrained("jinaai/jina-embeddings-v2-base-en", trust_remote_code=True)

def embed_text(text):
    inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
    with torch.no_grad():
        embeddings = embedding_model(**inputs).pooler_output
    vec = embeddings[0].cpu().numpy()
    norm = np.linalg.norm(vec)
    if norm == 0:
        return vec.tolist()
    return (vec / norm).tolist()

pc = Pinecone(api_key=config.PINECONE_API_KEY)
index = pc.Index(config.PINECONE_INDEX_NAME)
driver = GraphDatabase.driver(config.NEO4J_URI, auth=(config.NEO4J_USER, config.NEO4J_PASSWORD))

def pinecone_query(query_text, top_k=5):
    vec = embed_text(query_text)
    res = index.query(vector=vec, top_k=top_k, include_metadata=True, include_values=False)
    return res["matches"]

def fetch_graph_context(node_ids, neighborhood_depth=1):
    facts = []
    with driver.session() as session:
        for nid in node_ids:
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
    return facts

def build_prompt(user_query, pinecone_matches, graph_facts):
    system = (
        "You are a helpful travel assistant. Use the provided semantic search results "
        "and graph facts to answer the user's query briefly and concisely. "
        "Cite node ids when referencing specific places or attractions."
    )
    vec_context = []
    for m in pinecone_matches:
        meta = m["metadata"]
        score = m.get("score", None)
        snippet = f"- id: {m['id']}, name: {meta.get('name','')}, type: {meta.get('type','')}, score: {score}"
        if meta.get("city"):
            snippet += f", city: {meta.get('city')}"
        vec_context.append(snippet)
    graph_context = [
        f"- ({f['source']}) -[{f['rel']}]-> ({f['target_id']}) {f['target_name']}: {f['target_desc']}"
        for f in graph_facts
    ]
    prompt = [
        {"role": "system", "content": system},
        {"role": "user", "content":
            f"User query: {user_query}\n\n"
            "Top semantic matches (from vector DB):\n" + "\n".join(vec_context[:10]) + "\n\n"
            "Graph facts (neighboring relations):\n" + "\n".join(graph_context[:20]) + "\n\n"
            "Based on the above, answer the user's question. If helpful, suggest 2–3 concrete itinerary steps or tips and mention node ids for references."
        }
    ]
    return prompt

def call_groq_chat(prompt_messages):
    url = "https://api.groq.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "llama3-70b-8192",  # or your preferred Groq model
        "messages": prompt_messages,
        "max_tokens": 600,
        "temperature": 0.2
    }
    response = requests.post(url, headers=headers, json=data)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]

def interactive_chat():
    print("Hybrid travel assistant. Type 'exit' to quit.")
    while True:
        query = input("\nEnter your travel question: ").strip()
        if not query or query.lower() in ("exit", "quit"):
            break
        matches = pinecone_query(query, top_k=5)
        match_ids = [m["id"] for m in matches]
        graph_facts = fetch_graph_context(match_ids)
        prompt = build_prompt(query, matches, graph_facts)
        answer = call_groq_chat(prompt)
        print("\n=== Assistant Answer ===\n")
        print(answer)
        print("\n=== End ===\n")

if __name__ == "__main__":
    interactive_chat()
