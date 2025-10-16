import os
from dotenv import load_dotenv

# Load variables from .env
load_dotenv()

# Neo4j
NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USER = os.getenv("NEO4J_USER")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE")
AURA_INSTANCEID = os.getenv("AURA_INSTANCEID")
AURA_INSTANCENAME = os.getenv("AURA_INSTANCENAME")

# Groq
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Pinecone
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_ENV = os.getenv("PINECONE_ENV")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME")
PINECONE_VECTOR_DIM = int(os.getenv("PINECONE_VECTOR_DIM", 768))
PINECONE_FIELD_MAP = dict([kv.split(":") for kv in os.getenv("PINECONE_FIELD_MAP","text:chunk_text").split(",")])
PINECONE_CLOUD = "aws"        
PINECONE_REGION = "us-east-1"

# Performance Tuning (NEW)
SCORE_THRESHOLD = 0.7  # Minimum similarity score for Pinecone results
CACHE_MAX_SIZE = 1000  # Maximum number of cached embeddings