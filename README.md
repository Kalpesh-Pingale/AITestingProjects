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

### AI Social Media Content Creation
`AI_Social_Media_Content_Creation/` — Fill-in-the-blank content templates that turn one idea into a publish-ready pack for every platform. Plan once with the Hook · Story · Offer worksheet, then repurpose it into YouTube, Instagram (Reel / Post / Carousel), Medium, blog, and LinkedIn pieces. Each template carries its own format, voice rules, hook patterns, skeleton, and pre-publish checklist — designed to be pasted into an AI assistant alongside the plan.

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
│   └── ex_03_Literals/
├── AI_Social_Media_Content_Creation/  # Content templates (plan once, repurpose everywhere)
│   ├── 00_Hook_Story_Offer_Planning.md
│   ├── 01_YouTube_Video_Template.md
│   ├── 02_Instagram_Reel_Template.md
│   ├── 03_Instagram_Post_Template.md
│   ├── 04_Instagram_Carousel_Template.md
│   ├── 05_Medium_Article_Template.md
│   ├── 06_Blog_Post_Template.md
│   └── 07_LinkedIn_Post_Template.md
├── CrewAI/                          # Test Analyst agent (CrewAI + Groq)
│   ├── Test_Analyst_Agent.py
│   ├── requirements.txt
│   └── README.md
└── README.md
```
