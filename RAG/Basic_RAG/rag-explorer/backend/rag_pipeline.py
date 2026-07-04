import os
import tempfile
import uuid
from pathlib import Path
from typing import List, Optional

import chromadb
import fitz  # PyMuPDF
from dotenv import load_dotenv
from groq import Groq
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sentence_transformers import SentenceTransformer

load_dotenv()

CHROMA_DB_PATH = Path(__file__).parent / "chroma_db"
COLLECTION_NAME = "rag_explorer"
CHUNK_SIZE = 500
CHUNK_OVERLAP = 100
TOP_K = 4

# Groq config — defaulting to openai/gpt-oss-120b (OpenAI GPT-OSS 120B).
# Set GROQ_MODEL env var to override.
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

# Embedding model: Nomic Embed Text v1.5 (runs locally via sentence-transformers)
EMBEDDING_MODEL_NAME = os.getenv(
    "EMBEDDING_MODEL", "all-MiniLM-L6-v2"
)


class RAGPipeline:
    """End-to-end RAG pipeline: ingest PDF → chunk → embed → store → retrieve → answer."""

    def __init__(self):
        self._embedder: Optional[SentenceTransformer] = None
        self._chroma_client: Optional[chromadb.PersistentClient] = None
        self._groq_client: Optional[Groq] = None
        self._collection: Optional[chromadb.Collection] = None

        # Track state for the UI flow visualization
        self.last_ingestion = {}  # metadata from last ingestion run
        self.last_query = {}  # metadata from last query run

    # ------------------------------------------------------------------ #
    #  Lazy-init helpers
    # ------------------------------------------------------------------ #

    @property
    def embedder(self) -> SentenceTransformer:
        if self._embedder is None:
            self._embedder = SentenceTransformer(EMBEDDING_MODEL_NAME)
        return self._embedder

    @property
    def chroma_client(self) -> chromadb.PersistentClient:
        if self._chroma_client is None:
            self._chroma_client = chromadb.PersistentClient(
                path=str(CHROMA_DB_PATH)
            )
        return self._chroma_client

    @property
    def groq_client(self) -> Groq:
        if self._groq_client is None:
            api_key = os.getenv("GROQ_API_KEY")
            if not api_key:
                raise ValueError(
                    "GROQ_API_KEY environment variable is not set. "
                    "Create a .env file or set it in your environment."
                )
            self._groq_client = Groq(api_key=api_key)
        return self._groq_client

    @property
    def collection(self) -> chromadb.Collection:
        if self._collection is None:
            self._collection = self.chroma_client.get_or_create_collection(
                name=COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            )
        return self._collection

    # ------------------------------------------------------------------ #
    #  PDF extraction
    # ------------------------------------------------------------------ #

    def extract_text_from_pdf(self, pdf_path: str) -> str:
        """Extract all text from a PDF file."""
        doc = fitz.open(pdf_path)
        text_parts = []
        for page_num, page in enumerate(doc, 1):
            page_text = page.get_text()
            if page_text.strip():
                text_parts.append(page_text)
        doc.close()
        return "\n\n".join(text_parts)

    # ------------------------------------------------------------------ #
    #  Chunking
    # ------------------------------------------------------------------ #

    def chunk_text(self, text: str) -> List[str]:
        """Split text into overlapping chunks."""
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
            separators=["\n\n", "\n", ". ", " ", ""],
            length_function=len,
        )
        return splitter.split_text(text)

    # ------------------------------------------------------------------ #
    #  Embedding
    # ------------------------------------------------------------------ #

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a list of text strings."""
        embeddings = self.embedder.encode(texts, show_progress_bar=False)
        return embeddings.tolist()

    # ------------------------------------------------------------------ #
    #  Storage (ChromaDB)
    # ------------------------------------------------------------------ #

    def store_chunks(
        self, chunks: List[str], doc_name: str, embeddings: List[List[float]]
    ) -> int:
        """Store chunk embeddings in ChromaDB. Returns count of stored chunks."""
        ids = [str(uuid.uuid4()) for _ in chunks]
        metadatas = [
            {"doc_name": doc_name, "chunk_index": i, "text": chunks[i]}
            for i in range(len(chunks))
        ]
        self.collection.add(
            embeddings=embeddings,
            documents=chunks,
            metadatas=metadatas,
            ids=ids,
        )
        return len(chunks)

    # ------------------------------------------------------------------ #
    #  Retrieval
    # ------------------------------------------------------------------ #

    def retrieve(self, query: str, k: int = TOP_K) -> List[dict]:
        """Retrieve the top-k most relevant chunks for a query."""
        query_embedding = self.embed_texts([query])[0]
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=k,
            include=["documents", "metadatas", "distances"],
        )
        retrieved = []
        if results["documents"] and results["documents"][0]:
            for i, doc in enumerate(results["documents"][0]):
                retrieved.append(
                    {
                        "text": doc,
                        "score": round(
                            1 - (results["distances"][0][i] if results["distances"] else 0),
                            4,
                        ),
                        "metadata": results["metadatas"][0][i]
                        if results["metadatas"]
                        else {},
                    }
                )
        return retrieved

    # ------------------------------------------------------------------ #
    #  Answer generation (Groq)
    # ------------------------------------------------------------------ #

    def generate_answer(self, query: str, context_chunks: List[dict]) -> str:
        """Generate a final answer using Groq LLM, grounded on retrieved chunks."""
        context_text = "\n\n".join(
            f"[Chunk {i+1}]: {c['text']}" for i, c in enumerate(context_chunks)
        )
        system_prompt = (
            "You are a helpful RAG assistant. Answer the user's question based "
            "strictly on the provided context chunks. If the context does not "
            "contain enough information, say so. Be concise and accurate."
        )
        prompt = f"""Context:
{context_text}

Question: {query}

Answer based on the context above:"""

        response = self.groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=1024,
        )
        return response.choices[0].message.content

    # ------------------------------------------------------------------ #
    #  High-level steps
    # ------------------------------------------------------------------ #

    def ingest(self, pdf_path: str) -> dict:
        """Run full ingestion pipeline. Returns metadata for the UI."""
        # 1. Extract
        raw_text = self.extract_text_from_pdf(pdf_path)

        # 2. Chunk
        chunks = self.chunk_text(raw_text)

        # 3. Embed
        embeddings = self.embed_texts(chunks)

        # 4. Store
        doc_name = Path(pdf_path).name
        count = self.store_chunks(chunks, doc_name, embeddings)

        self.last_ingestion = {
            "doc_name": doc_name,
            "total_chars": len(raw_text),
            "num_chunks": count,
            "model": EMBEDDING_MODEL_NAME,
        }
        return self.last_ingestion

    def query(self, question: str) -> dict:
        """Run full query pipeline: retrieve + generate. Returns result for the UI."""
        # 1. Retrieve
        retrieved_chunks = self.retrieve(question)
        if not retrieved_chunks:
            return {
                "question": question,
                "answer": "No relevant chunks found. Please ingest a document first.",
                "chunks": [],
                "llm_model": GROQ_MODEL,
                "embedding_model": EMBEDDING_MODEL_NAME,
            }

        # 2. Generate
        answer = self.generate_answer(question, retrieved_chunks)

        self.last_query = {
            "question": question,
            "answer": answer,
            "chunks": retrieved_chunks,
            "llm_model": GROQ_MODEL,
            "embedding_model": EMBEDDING_MODEL_NAME,
        }
        return self.last_query

    def stats(self) -> dict:
        """Return basic statistics about stored documents."""
        count = self.collection.count()
        return {
            "chunk_count": count,
            "embedding_model": EMBEDDING_MODEL_NAME,
            "llm_model": GROQ_MODEL,
        }

    def reset(self) -> None:
        """Delete the collection and start fresh."""
        try:
            self.chroma_client.delete_collection(COLLECTION_NAME)
        except Exception:
            pass
        self._collection = None
        self.last_ingestion = {}
        self.last_query = {}
