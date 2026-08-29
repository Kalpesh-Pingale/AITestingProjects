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

### CrewAI — QA Agent Suite
`CrewAI/` — A set of CrewAI agents for QA workflows, powered by Groq LLM (openai/gpt-oss-120b):

- **`01_Test_Analyst_Agent.py`** — Single agent that plays senior QA engineer: give it a feature or requirement and it produces 5–10 prioritized test cases (functional, negative, security, edge cases).
- **`02_Requirements_Clarifier_Agent.py`** — 3-agent crew that pulls a user story from Jira (REST API), audits it for ambiguity, missing acceptance criteria, undefined error handling, and INVEST/testability gaps, then generates targeted clarification questions and rewritten Given/When/Then criteria. Run with `--issue SHOP-1` (any key) and `--post` to write the report back as a Jira comment.
- **`03_Test_Strategy_Agent`** — 3-agent crew (Strategy Analyst → Tool Recommender → Strategy Writer) that turns project metadata into a full ISTQB-aligned test strategy document.

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
├── CrewAI/                          # QA agent suite (CrewAI + Groq)
│   ├── 01_Test_Analyst_Agent.py     # Test-case generator
│   ├── 02_Requirements_Clarifier_Agent.py  # Jira user-story clarifier (3-agent crew)
│   ├── 03_Test_Strategy_Agent       # ISTQB test-strategy builder (3-agent crew)
│   └── requirements.txt
└── README.md
```
