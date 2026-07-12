# RAG Explorer

An end-to-end **Retrieval-Augmented Generation** (RAG) pipeline with a React UI.

**Flow:** PDF → Chunking → Embedding (all-MiniLM-L6-v2) → ChromaDB → Retrieval → Groq (openai/gpt-oss-120b) → Answer

## Architecture

```
rag-explorer/
├── backend/              # Python FastAPI server
│   ├── main.py           # API endpoints (ingest, query, stats, reset)
│   ├── rag_pipeline.py   # Core RAG pipeline logic
│   └── requirements.txt  # Python dependencies
├── frontend/             # React / Vite app
│   └── src/              # Components & styles
├── .env.example
└── README.md
```

## Prerequisites

- **Python 3.10+**
- **Node.js 18+**
- A **Groq API key** ([get one here](https://console.groq.com/keys))

## Setup

### 1. Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate    # Linux/macOS
# venv\Scripts\activate     # Windows

pip install -r requirements.txt
```

Create `backend/.env` with your Groq key:

```
GROQ_API_KEY=gsk_your_key_here
```

### 2. Frontend

```bash
cd frontend
npm install
```

## Run

### Terminal 1 — Backend

```bash
cd backend
venv\Scripts\Activate.ps1  ### Use this command in powershell.
source venv/bin/activa
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Terminal 2 — Frontend

```bash
cd frontend
npm run dev
```

Open **http://localhost:5173** in your browser.

## Usage

1. **Ingest** – Upload a PDF. The backend extracts text, chunks it (500 chars, 100 overlap),
   generates embeddings (`all-MiniLM-L6-v2` via sentence-transformers), and stores
   them in ChromaDB (local persistent vector DB).
2. **Query** – Ask a question. The pipeline retrieves the top 4 most relevant
   chunks from ChromaDB and sends them (with the question) to Groq's `openai/gpt-oss-120b`
   model for answer generation.
3. **Explore** – The UI shows every step: ingestion stats, retrieved chunks
   with similarity scores, and the final answer.

## Configuration

| Env variable | Default | Description |
|---|---|---|
| `GROQ_API_KEY` | — | Groq API key (required) |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | Groq LLM for answer generation |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Sentence‑Transformers model for local embeddings |

> **Note:** You can switch the embedding model to `nomic-ai/nomic-embed-text-v1.5` by setting `EMBEDDING_MODEL` in `backend/.env` (requires ~700MB download on first use).

## Tech Stack
- **PyMuPDF** – PDF text extraction
- **LangChain Text Splitters** – Recursive character text chunking (500 chars, 100 overlap)
- **sentence-transformers** – `all-MiniLM-L6-v2` local embeddings (384-dim)
- **ChromaDB** – Local persistent vector database (cosine similarity)
- **Groq** – Fast LLM inference via `openai/gpt-oss-120b`
- **FastAPI** – Python backend server
- **React / Vite** – Frontend UI
