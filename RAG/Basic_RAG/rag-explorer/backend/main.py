import shutil
import tempfile
import threading
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from rag_pipeline import RAGPipeline

app = FastAPI(title="RAG Explorer API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

pipeline = RAGPipeline()


@app.on_event("startup")
async def warmup():
    """Pre-load the embedding model in the background so the first request is fast."""
    def _load():
        try:
            _ = pipeline.embedder
            print("Embedding model loaded at startup.")
        except Exception as e:
            print(f"Warning: Could not pre-load embedding model: {e}")
    threading.Thread(target=_load, daemon=True).start()


# ------------------------------------------------------------------ #
#  Data models
# ------------------------------------------------------------------ #


class QueryRequest(BaseModel):
    question: str


class QueryResponse(BaseModel):
    question: str
    answer: str
    chunks: list
    llm_model: str
    embedding_model: str


class IngestionResponse(BaseModel):
    doc_name: str
    total_chars: int
    num_chunks: int
    model: str


class StatsResponse(BaseModel):
    chunk_count: int
    embedding_model: str
    llm_model: str


# ------------------------------------------------------------------ #
#  Endpoints
# ------------------------------------------------------------------ #


@app.get("/", tags=["info"])
async def root():
    return {"app": "RAG Explorer", "status": "running"}


@app.get("/api/stats", response_model=StatsResponse)
async def get_stats():
    return pipeline.stats()


@app.get("/api/last-ingestion")
async def get_last_ingestion():
    return pipeline.last_ingestion


@app.get("/api/last-query")
async def get_last_query():
    return pipeline.last_query


@app.post("/api/ingest", response_model=IngestionResponse)
async def ingest_pdf(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are accepted.")

    # Save upload to a temp file and ingest
    tmp_dir = Path(tempfile.mkdtemp())
    tmp_path = tmp_dir / file.filename
    try:
        with open(tmp_path, "wb") as f:
            content = await file.read()
            f.write(content)
        result = pipeline.ingest(str(tmp_path))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return result


@app.post("/api/query", response_model=QueryResponse)
async def query(body: QueryRequest):
    if not body.question.strip():
        raise HTTPException(400, "Question cannot be empty.")
    return pipeline.query(body.question.strip())


@app.post("/api/reset")
async def reset():
    pipeline.reset()
    return {"status": "reset ok"}
