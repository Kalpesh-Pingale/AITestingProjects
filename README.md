# AITesterBlueprint

A collection of AI testing and exploration projects.

## Projects

### RAG Explorer
`RAG/Basic_RAG/rag-explorer/` — An end-to-end Retrieval-Augmented Generation pipeline with a React UI. Upload a PDF, get answers via chunking, embeddings (all-MiniLM-L6-v2), ChromaDB vector storage, and Groq LLM (openai/gpt-oss-120b).

### Langflow
`langflow/` — Langflow-based agents and workflows.

## Structure

```
├── RAG/                        # RAG-related projects
│   └── Basic_RAG/
│       ├── rag-explorer/       # Full-stack RAG app (FastAPI + React)
│       ├── data/               # Source documents
│       └── prompt/             # Prompt templates
├── langflow/                   # Langflow agents
└── README.md
```
