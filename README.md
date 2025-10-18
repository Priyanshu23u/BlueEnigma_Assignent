# 🧠 Hybrid AI Travel Assistant Challenge

### Goal
Build and debug a hybrid AI assistant that answers travel queries using:
- **Pinecone** (semantic vector DB)
- **Neo4j** (graph context)
- **Groq** Chat Models (Llama 3.3-70B)

This project implements a **Retrieval-Augmented Generation (RAG)** system that combines vector search with knowledge graph traversal to provide intelligent, context-aware travel recommendations for Vietnam.

---

## 📋 Prerequisites
### Note : Groq Chat model is used as OpenAI's Chat model is not free 
Before starting, ensure you have:
- Python 3.8 or higher
- Pinecone account with API key
- Neo4j AuraDB instance
- Groq API key
- Git installed

---


---

## 📊 Project Structure
```bash
BlueEnigma_Assignment/
├── app.py # Flask web app (bonus)
├── config.py # Configuration
├── requirements.txt # Dependencies
├── .env # API keys (don't commit!)
├── README.md # This file
│
├── data/
│ └── vietnam_travel_dataset.json
│
├── scripts/
│ ├── hybrid_chat.py # Main chat script
│ ├── load_to_neo4j.py # Neo4j loader
│ ├── pinecone_upload.py # Pinecone uploader
│ └── visualize_graph.py # Graph visualization
│
├── templates/ # Web UI (bonus)
│ └── index.html
│
├── static/ # CSS/JS (bonus)
│ ├── css/style.css
│ └── js/script.js
│
└── improvements/
└── improvements.md # Your documentation
```


## 🚀 Quick Start

### Step 1: Clone and Setup
Clone the repository
git clone <your-repo-url>
cd vietnam-travel-hybrid-ai

Create virtual environment
python -m venv venv

Activate virtual environment
On Windows:
venv\Scripts\activate

On macOS/Linux:
source venv/bin/activate

Install dependencies
pip install -r requirements.txt


### Step 2: Configure API Keys

Create a `.env` file in the project root and add your credentials:
Neo4j AuraDB
NEO4J_URI=neo4j+s://your-instance.databases.neo4j.io
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password
NEO4J_DATABASE=neo4j

Groq API
GROQ_API_KEY=your_groq_api_key

Pinecone
PINECONE_API_KEY=your_pinecone_api_key
PINECONE_INDEX_NAME=vietnam-travel
PINECONE_VECTOR_DIM=768


### Step 3: Load Data to Neo4j
python scripts/load_to_neo4j.py


### Step 4: Visualize the Graph (Optional)
python scripts/visualize_graph.py

This generates `neo4j_viz.html` which you can open in your browser to explore the knowledge graph structure.

### Step 5: Upload Embeddings to Pinecone
python scripts/pinecone_upload.py


### Step 6: Run the Hybrid Chat
python scripts/hybrid_chat.py


### Step 7: Test with Sample Query
Type the following query:


## 🌐 Web Interface (Bonus)

For a modern web interface with interactive graph visualization:
python app.py


Then open `http://localhost:5000` in your browser.

**Features:**
- 💬 Interactive chat interface
- 🗺️ Real-time knowledge graph visualization
- 📊 Context-aware responses with citations
- 🎨 Beautiful, responsive UI

---


