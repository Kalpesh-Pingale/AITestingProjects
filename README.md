# AITesterBlueprint

A collection of AI testing and exploration projects.

## Projects

### RAG Explorer
`RAG/Basic_RAG/rag-explorer/` — An end-to-end Retrieval-Augmented Generation pipeline with a React UI. Upload a PDF, get answers via chunking, embeddings (all-MiniLM-L6-v2), ChromaDB vector storage, and Groq LLM (openai/gpt-oss-120b).

`RAG/Advance_RAG/` — Advanced RAG techniques and experiments.

### Langflow
`langflow/` — Langflow-based agents and workflows.

### Python Learning
`Python_Learning/` — Python fundamentals practice, organized by topic (basics, keywords/identifiers/variables, literals).

## Structure

```
├── RAG/                             # RAG-related projects
│   ├── Basic_RAG/
│   │   ├── rag-explorer/            # Full-stack RAG app (FastAPI + React)
│   │   ├── data/                    # Source documents
│   │   └── prompt/                  # Prompt templates
│   └── Advance_RAG/                 # Advanced RAG experiments
├── langflow/                        # Langflow agents
├── Python_Learning/                 # Python practice exercises
│   ├── ex_01_Basics/
│   ├── ex_02_Keywords_Identifier_Variables/
│   └── ex_03_Literals/
└── README.md
```
