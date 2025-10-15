import json
from neo4j import GraphDatabase
from tqdm import tqdm
import config
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

DATA_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data', 'vietnam_travel_dataset.json'))
driver = GraphDatabase.driver(config.NEO4J_URI, auth=(config.NEO4J_USER, config.NEO4J_PASSWORD))

def create_constraints(tx):
    tx.run("CREATE CONSTRAINT IF NOT EXISTS FOR (n:Entity) REQUIRE n.id IS UNIQUE")

def upsert_node(tx, node):
    labels = [node.get("type", "Unknown"), "Entity"]
    label_cypher = ":" + ":".join(labels)
    props = {k: v for k, v in node.items() if k != "connections"}
    tx.run(
        f"MERGE (n{label_cypher} {{id: $id}}) SET n += $props",
        id=node["id"], props=props
    )

def create_relationship(tx, source_id, rel):
    rel_type = rel.get("relation", "RELATED_TO")
    target_id = rel.get("target")
    if not target_id:
        return
    cypher = (
        "MATCH (a:Entity {id: $source_id}), (b:Entity {id: $target_id}) "
        f"MERGE (a)-[r:{rel_type}]->(b) RETURN r"
    )
    tx.run(cypher, source_id=source_id, target_id=target_id)

def main():
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        nodes = json.load(f)
    with driver.session() as session:
        session.execute_write(create_constraints)
        for node in tqdm(nodes, desc="Creating nodes"):
            session.execute_write(upsert_node, node)
        for node in tqdm(nodes, desc="Creating relationships"):
            conns = node.get("connections", [])
            for rel in conns:
                session.execute_write(create_relationship, node["id"], rel)
    print("Done loading into Neo4j.")

if __name__ == "__main__":
    main()
