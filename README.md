# AITesterBlueprint

A collection of AI testing and exploration projects.

## Projects

### RAG Explorer
`RAG/Basic_RAG/rag-explorer/` — An end-to-end Retrieval-Augmented Generation pipeline with a React UI. Upload a PDF, get answers via chunking, embeddings (all-MiniLM-L6-v2), ChromaDB vector storage, and Groq LLM (openai/gpt-oss-120b).

`RAG/Advance_RAG/` — Advanced RAG techniques and experiments.

### Langflow
`langflow/` — Langflow-based agents and workflows.

### Python Learning
`Python_Learning/` — Python fundamentals practice, organized by topic: basics, keywords/identifiers/variables, literals, operators, conditionals & loops, switch/match, functions & scopes, decorators, type conversion, lambda expressions, lists, and tuples.

### CrewAI — Test Analyst Agent
`CrewAI/` — A CrewAI agent that plays senior QA engineer: give it a feature or requirement and it produces 5–10 prioritized test cases (functional, negative, security, edge cases), powered by Groq LLM (openai/gpt-oss-120b).

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
│   ├── ex_03_Literals/
│   ├── ex_04_Operators/
│   ├── ex_05_Condition_Loops/
│   ├── ex_06_Switch_Match/
│   ├── ex_07_Loops/
│   ├── ex_08_Functions/
│   ├── ex_09_Functions_Scopes/
│   ├── ex_10_Decorators/
│   ├── ex_11_TypeConversion/
│   ├── ex_12_Lambda_Exp/
│   ├── ex_13_LIST/
│   └── ex_14_Tuple/
├── CrewAI/                          # Test Analyst agent (CrewAI + Groq)
│   ├── Test_Analyst_Agent.py
│   ├── requirements.txt
│   └── README.md
└── README.md
```
