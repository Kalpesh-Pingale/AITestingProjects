# Jira QA Crew — AI-Powered QA Artifact Generator

Enter one or more Jira ticket ids and get a reviewable QA pack: requirement
analysis, a twelve section test plan, detailed test cases, Playwright
TypeScript automation, a traceability matrix, and downloadable Markdown, CSV,
JSON, TypeScript and ZIP artifacts.

The engine is CrewAI. Four real agents run sequentially per ticket, each
producing a validated Pydantic object. Jira is read through an MCP server
first and the Jira Cloud REST API second. Everything the model must not decide
— which provider answers, whether a stage passed, how coverage is computed,
what is written to disk — is deterministic Python.

---

## Contents

- [Product overview](#product-overview)
- [Architecture](#architecture)
- [Pipeline](#pipeline)
- [Agent responsibilities](#agent-responsibilities)
- [Repository structure](#repository-structure)
- [Local installation](#local-installation)
- [Environment configuration](#environment-configuration)
  - [Which credential does what](#which-credential-does-what)
- [Jira MCP setup](#jira-mcp-setup)
  - [Reusing an MCP server you already run in an IDE](#reusing-an-mcp-server-you-already-run-in-an-ide)
- [Jira REST fallback setup](#jira-rest-fallback-setup)
- [Running the app](#running-the-app)
- [Demo mode](#demo-mode)
- [Artifacts](#artifacts)
- [Tests](#tests)
- [Troubleshooting](#troubleshooting)
- [Security notes](#security-notes)
- [Limitations](#limitations)
- [Deployment](#deployment)

---

## Product overview

The manual workflow this replaces: open Jira, read the story, interpret the
requirements, write a plan, write test cases, decide what to automate, write
Playwright specs, build traceability, export and share.

The app automates that while keeping the human review points visible. It
separates what the ticket **states** from what was **inferred**, and refuses to
fill gaps with plausible invention — missing information is reported, not
guessed.

It does **not** update Jira, transition issues, create bugs, or execute
Playwright. It is a generation and review tool; every artifact is meant to be
read by a QA engineer before use.

---

## Architecture

```text
Streamlit UI  (app.py, ui/)          presentation only
      │
      ▼
QAPipeline    (services/pipeline.py) deterministic orchestration
      │
      ├── JiraGateway (jira/)        provider choice: MCP → REST, in Python
      │      ├── JiraMCPProvider     contained MCP client, read-only
      │      ├── JiraRestProvider    GET /rest/api/3/issue/{key}
      │      └── JiraDemoProvider    fixtures, only when DEMO_MODE=true
      │
      ├── Crew (crew/)               4 CrewAI agents, Process.sequential
      │      ├── prompts/*.yaml      all prompts live outside the UI
      │      └── guardrails.py       deterministic validation per stage
      │
      └── services/                  traceability, renderers, artifacts
```

Key decisions:

| Decision | Why |
| --- | --- |
| One `Crew` per ticket, four `Task`s chained with `context=` | Each stage depends on the previous **validated** output; a fresh crew per ticket makes cross-ticket leakage structurally impossible. |
| Validation runs as a CrewAI **task guardrail** with `guardrail_max_retries=1` | Deterministic checks execute inside the crew, and a malformed structured output gets exactly one repair attempt — never an unbounded retry loop. |
| The issue is pre-fetched by the gateway and injected into the analyst prompt, with `fetch_jira_issue` still available as a tool | The provider decision stays application logic, a Jira outage fails before any LLM spend, and the source (`MCP`/`REST`) is recorded from the actual fetch rather than inferred from model output. |
| A contained MCP client instead of handing raw MCP tools to the agent | The `mcps` DSL lets the model choose tools; the required MCP → REST fallback must be deterministic, and only approved read-only tools may ever be called. |
| Renderers are pure Python over Pydantic objects | Raw LLM markdown is never the source of truth, so artifacts are reproducible byte-for-byte from the same validated objects. |
| Coverage computed in `services/traceability.py` | The model never grades its own coverage. |

---

## Pipeline

```text
Jira IDs → parse / normalise / de-duplicate
   ↓  (per ticket, isolated)
JiraGateway.fetch          MCP → REST, source recorded
   ↓
Jira Analyst Agent         → RequirementAnalysis   → validated
   ↓
Test Plan Writer Agent     → TestPlan              → validated
   ↓
Test Case Writer Agent     → TestCaseSuite         → validated
   ↓
Playwright Coder Agent     → PlaywrightBundle      → normalised + validated
   ↓
Traceability + coverage (deterministic Python)
   ↓
Artifacts on disk  →  Streamlit results and downloads
```

A ticket that fails does not stop the others. A run is successful when at
least one ticket completes; a ticket is **never** marked successful when a
required output is missing — partial artifacts are still written for review
and the ticket is reported as failed.

---

## Agent responsibilities

| # | Agent | Output model | Validated for |
| --- | --- | --- | --- |
| 1 | Jira Analyst (only agent with Jira access) | `RequirementAnalysis` | ticket identity, `REQ-###` / `AC-###` format, duplicates, unknown references, EXPLICIT items actually grounded in the ticket text |
| 2 | Test Plan Writer | `TestPlan` | exactly 12 sections with content, scenarios resolving to real REQ/AC ids, unreferenced requirements |
| 3 | Test Case Writer | `TestCaseSuite` | `KEY-TC-###` ids, duplicates, steps and expected results, traceability, every explicit AC covered or explicitly declared uncovered |
| 4 | Playwright Coder | `PlaywrightBundle` | compilable spec files, no `waitForTimeout`, no XPath, no hard-coded URLs or credentials, mappings to real cases, honest `READY` / `NEEDS_CONFIGURATION` |

Errors fail the stage (after one repair attempt). Warnings are surfaced in the
UI and artifacts and downgrade the ticket to `COMPLETED_WITH_WARNINGS`.

---

## Repository structure

```text
Crew_AI_QA_Pipeline/
├── app.py                         Streamlit entry point (presentation only)
├── src/jira_qa_crew/
│   ├── config.py                  env + st.secrets settings, readiness checks
│   ├── models.py                  every Pydantic model
│   ├── exceptions.py              typed errors
│   ├── logging_utils.py           structured logging + secret redaction
│   ├── tickets.py                 ticket id parsing / normalisation
│   ├── jira/
│   │   ├── adf.py                 Atlassian Document Format → text
│   │   ├── base.py                provider contract + payload normalisation
│   │   ├── mcp_provider.py        MCP client, tool discovery, read-only guard
│   │   ├── rest_provider.py       Jira Cloud REST, retries, typed errors
│   │   ├── demo_provider.py       fixtures (DEMO_MODE only)
│   │   ├── gateway.py             deterministic MCP → REST fallback
│   │   └── textify.py             untrusted-data framing for prompts
│   ├── tools/jira_tool.py         FetchJiraIssueTool (read-only, key-scoped)
│   ├── crew/
│   │   ├── agents.py tasks.py factory.py
│   │   ├── guardrails.py          validation wired into CrewAI
│   │   ├── callbacks.py           real stage progress from the event bus
│   │   └── llm.py                 configurable model
│   ├── prompts/agents.yaml tasks.yaml
│   ├── services/
│   │   ├── pipeline.py validation.py traceability.py
│   │   ├── renderers.py           deterministic md / csv / json
│   │   └── artifacts.py           safe paths, files, ZIP
│   └── ui/ state.py components.py results.py
├── tests/                         190 tests (4 opt-in integration)
├── fixtures/jira/                 demo tickets
├── outputs/                       generated runs (git-ignored)
├── requirements.txt pyproject.toml Dockerfile docker-compose.yml
└── .streamlit/config.toml .streamlit/secrets.toml.example
```

---

## Local installation

Requires Python 3.11+ (developed on 3.12).

```bash
cd Crew_AI_QA_Pipeline
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # macOS / Linux

pip install -r requirements.txt
pip install -e ".[dev]"            # tests and linting
cp .env.example .env               # then fill it in
```

If your LLM provider is not one CrewAI routes natively, also
`pip install litellm`.

---

## Environment configuration

Configuration comes from process environment variables, then `.env`, then
`st.secrets` — real environment variables always win. See
[`.env.example`](.env.example) for the full annotated list and
[`.streamlit/secrets.toml.example`](.streamlit/secrets.toml.example) for the
Streamlit Cloud form.

Minimum for a live run:

```dotenv
LLM_MODEL=openai/gpt-4.1-mini
LLM_API_KEY=...

JIRA_INTEGRATION_MODE=auto
JIRA_URL=https://your-domain.atlassian.net
JIRA_EMAIL=you@example.com
JIRA_API_TOKEN=...
```

`LLM_MODEL` is deliberately not hard-coded anywhere in the code — provider
naming changes and the app must follow it without an edit. Groq, for example:

```dotenv
LLM_MODEL=openai/gpt-oss-120b
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_API_KEY=gsk_...
```

Configuration is validated before a run starts; problems are reported as
actionable messages in the UI, never as a stack trace.

### Which credential does what

There are three independent credentials, and they are not interchangeable:

| Credential | Variables | Used by | Not used by |
| --- | --- | --- | --- |
| LLM provider key | `LLM_API_KEY` (+ `LLM_BASE_URL`) | every agent stage | Jira, MCP |
| Jira API token | `JIRA_EMAIL` + `JIRA_API_TOKEN`, or `JIRA_BEARER_TOKEN` | the **REST** provider only ([rest_provider.py:97](src/jira_qa_crew/jira/rest_provider.py#L97)) | MCP |
| MCP server auth | `JIRA_MCP_HEADERS_JSON` (http/sse) or `JIRA_MCP_ENV_JSON` (stdio) | the **MCP** provider only ([mcp_provider.py:173-192](src/jira_qa_crew/jira/mcp_provider.py#L173-L192)) | REST |

The common misconception is that `JIRA_API_TOKEN` is what MCP authenticates
with. It is not — the app never forwards it to an MCP server. MCP gets exactly
the headers or child-process environment you configure, and nothing else. If
you want an MCP server to use your Jira API token, you have to put it there
yourself (see below).

---

## Jira MCP setup

The app talks to your Jira MCP server itself, so it works with servers that
disagree about tool names and argument schemas.

```dotenv
JIRA_MCP_TRANSPORT=streamable_http          # or sse, or stdio
JIRA_MCP_URL=https://your-mcp-host/mcp
JIRA_MCP_HEADERS_JSON={"Authorization":"<whatever your MCP server expects>"}
JIRA_MCP_GET_ISSUE_TOOL=                    # empty = auto-discover
JIRA_MCP_ISSUE_KEY_ARG=issueIdOrKey
JIRA_MCP_TIMEOUT_SECONDS=20
```

The `Authorization` value is passed through verbatim — usually `Bearer <token>`
for a token-based server, or `Basic <base64 of email:token>` for Atlassian's
hosted server with an API token.

For a local stdio server, the token goes into the child process's environment,
using whatever variable names *that server* documents:

```dotenv
JIRA_MCP_TRANSPORT=stdio
JIRA_MCP_COMMAND=npx
JIRA_MCP_ARGS_JSON=["-y","@your-org/jira-mcp-server"]
JIRA_MCP_ENV_JSON={"JIRA_URL":"https://your-domain.atlassian.net","JIRA_EMAIL":"you@example.com","JIRA_API_TOKEN":"ATATT..."}
```

### Reusing an MCP server you already run in an IDE

IDE MCP clients (VS Code's `mcp.json`, Claude Desktop, Cursor) keep their own
server list. This app does not read those files — it has no access to them and
they use a different schema — but the settings map across directly:

| IDE `mcp.json` | This app |
| --- | --- |
| `"type": "http"` + `"url"` | `JIRA_MCP_TRANSPORT=streamable_http` + `JIRA_MCP_URL` |
| `"type": "sse"` + `"url"` | `JIRA_MCP_TRANSPORT=sse` + `JIRA_MCP_URL` |
| `"command"` + `"args"` | `JIRA_MCP_TRANSPORT=stdio`, `JIRA_MCP_COMMAND`, `JIRA_MCP_ARGS_JSON` |
| `"env": { … }` | `JIRA_MCP_ENV_JSON={ … }` |
| an auth header | `JIRA_MCP_HEADERS_JSON={"Authorization":"…"}` |

Auth is the part that does not always transfer. IDE clients often implement
auth *modes* — an interactive OAuth flow, or an `apiToken` mode that builds the
header for you — and store the resulting token in the OS keychain rather than
in the JSON file. This app takes no auth modes: it sends the literal headers
you give it. So an IDE entry such as

```jsonc
{ "url": "https://mcp.atlassian.com/v1/mcp", "type": "http",
  "auth": { "method": "apiToken", "email": "you@example.com", "token": "ATATT..." } }
```

becomes an explicit Basic header here:

```dotenv
JIRA_MCP_TRANSPORT=streamable_http
JIRA_MCP_URL=https://mcp.atlassian.com/v1/mcp
JIRA_MCP_HEADERS_JSON={"Authorization":"Basic <base64 of email:token>"}
```

Generate the value without pasting the secret into a shell history file:

```bash
python -c "import base64,getpass;e=input('email: ');t=getpass.getpass('token: ');print('Basic '+base64.b64encode(f'{e}:{t}'.encode()).decode())"
```

If the server rejects that, it wants OAuth rather than an API token. There is
no way to reuse an IDE's interactive OAuth session from here — run in
`REST only` mode instead, which needs no MCP server at all.

Behaviour:

- If `JIRA_MCP_GET_ISSUE_TOOL` is empty the app lists the server's tools and
  picks the first read-only "get issue" tool it recognises.
- The argument name is taken from the tool's own input schema when it has one,
  otherwise from `JIRA_MCP_ISSUE_KEY_ARG`.
- Any tool whose name looks like a write operation (`create`, `update`,
  `delete`, `transition`, `assign`, `add_`, `admin`, …) is refused, even if you
  configure it explicitly.
- Connection failures, timeouts, missing tools and unusable payloads all
  produce typed, actionable errors — and, in `auto` mode, a REST fallback.

---

## Jira REST fallback setup

Uses `GET /rest/api/{version}/issue/{issueIdOrKey}` with `expand=names`, which
lets acceptance criteria be found by field *name* without hard-coding a custom
field id. Set `JIRA_ACCEPTANCE_CRITERIA_FIELD=customfield_10011` to pin it.

- `JIRA_AUTH_MODE=basic` → `JIRA_EMAIL` + `JIRA_API_TOKEN`
  (create one at <https://id.atlassian.com/manage-profile/security/api-tokens>)
- `JIRA_AUTH_MODE=bearer` → `JIRA_BEARER_TOKEN`

401/403 and 404 fail immediately; 408, 429 and 5xx are retried with
exponential backoff up to `JIRA_MAX_ATTEMPTS`. Only GET requests exist in this
codebase.

---

## Running the app

```bash
streamlit run app.py
```

Then:

1. Paste ticket ids — commas, semicolons, spaces and new lines all work
   (`VWO-48` / `VWO-49, VWO-50`). Ids are upper-cased, de-duplicated and
   validated against `JIRA_KEY_PATTERN`.
2. Pick **Auto (MCP then REST)**, **MCP only** or **REST only**.
3. Press **Analyze & Generate QA Pack**.
4. Watch the four agent stages report real progress, then read the results:
   one tab per ticket, six tabs inside each (Requirements Analysis, Test Plan,
   Test Cases, Playwright, Traceability, Run Details) with per-artifact
   downloads and a ZIP of the whole run.

---

## Demo mode

```dotenv
DEMO_MODE=true
```

Reads `fixtures/jira/<KEY>.json` (`VWO-48`, `VWO-49` ship with the repo)
instead of Jira. It still calls a real LLM. Demo runs are labelled everywhere:
the provider badge shows `DEMO`, the ticket carries a warning, and the run
summary records it.

Demo data is **never** an automatic fallback: with `DEMO_MODE=false`, a ticket
that no provider can fetch fails.

---

## Artifacts

```text
outputs/<run_id>/
├── run_summary.md
├── manifest.json
└── <TICKET_KEY>/
    ├── requirements_analysis.md / .json
    ├── test_plan.md
    ├── test_cases.md / .csv
    ├── traceability_matrix.csv / .md
    ├── playwright_tests.md
    ├── manifest.json
    └── playwright/tests/<ticket-key>.spec.ts   (+ pages/, fixtures/)
```

Every path segment is sanitised; ticket input cannot create arbitrary paths or
escape the run directory. ZIPs are built on demand and refused above 40 MB.

---

## Tests

```bash
pytest                      # 186 tests, integration deselected
pytest -m integration       # opt-in, needs real credentials
ruff check .
```

Covered: ticket parsing, ADF conversion, MCP success and tool-discovery rules,
MCP → REST fallback, REST-only and MCP-only modes, both-providers-failed, no
silent demo fallback, Pydantic validation and coercion, duplicate REQ/AC/TC
detection, traceability and coverage maths, markdown and CSV rendering,
artifact paths and ZIPs, secret redaction, partial multi-ticket success, the
real CrewAI wiring, and Streamlit rendering via `streamlit.testing.v1.AppTest`.

No automated test calls a live Jira instance or a paid LLM: the CrewAI stages
are replaced by a stub that plays back validated outputs, and `conftest.py`
strips credentials from the environment.

For the opt-in integration tests set a readable issue key:

```bash
INTEGRATION_JIRA_KEY=VWO-48 pytest -m integration
```

Generated Playwright code is verified by writing the fixture bundle to disk
and running `npx playwright test --list` against it (see Troubleshooting if
Node.js is unavailable).

---

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| "Configuration is incomplete" | `LLM_MODEL` or an API key is missing, or the selected mode has no provider configured. The message names the variable. |
| `Could not initialise the LLM '<model>'` | CrewAI does not route that id natively — `pip install litellm`, or use a natively supported model id. |
| MCP: "Could not identify a read-only 'get issue' tool" | The server names its tool something unexpected. Set `JIRA_MCP_GET_ISSUE_TOOL` (the error lists the read-only tools it saw). |
| MCP: "Configured MCP tool … looks like a write tool" | The app refuses write-shaped tools by design. Point it at a read tool. |
| MCP returns 401/403, or "exposed no tools" | `JIRA_MCP_HEADERS_JSON` is missing, malformed or holds the wrong auth scheme. `JIRA_API_TOKEN` is **not** forwarded to MCP — see [Which credential does what](#which-credential-does-what). |
| Every ticket falls back to REST | Expected when MCP is unconfigured or failing; the Run Details tab shows the attempt trail and the reason. |
| `Jira REST rejected the credentials (HTTP 401/403)` | Wrong email/token pair, or the account cannot browse the project. |
| Acceptance criteria come out empty | The custom field was not detected — set `JIRA_ACCEPTANCE_CRITERIA_FIELD` to the field id. |
| `Configuration error — Invalid configuration value: <VAR>` on startup | A malformed value in `.env` (for example `LLM_MAX_TOKENS=0c` instead of `0`). The message names the variable; the app refuses to start until it is fixed. |
| Stage fails with "could not be parsed into a valid … object" | The model failed the schema twice (original + one repair). Use a stronger model or lower the ticket size. |
| Ticket times out | Raise `PIPELINE_TICKET_TIMEOUT_SECONDS`. |
| Node.js unavailable | `npx playwright test --list` cannot run; the generated TypeScript structure is still validated in Python (imports, `test()`, locators, forbidden patterns), but compilation is unverified. |

---

## Security notes

- Secrets come from the environment or `st.secrets` only. The UI shows
  redacted status, never values, and no long-lived secret is collected in a
  text field.
- Every log record and user-facing error passes through `redact()`, which
  strips known secret values and secret-shaped tokens (`Bearer …`, `ATATT…`,
  `sk-…`, `gsk_…`, `password=…`).
- Jira access is read-only end to end: REST issues only GETs, and MCP tool
  names matching write verbs are refused.
- Jira content is treated as untrusted business data. It is wrapped in
  explicit untrusted-data delimiters with instructions never to obey it, and
  the fetch tool is scoped to a single ticket key, so an injected "read
  TICKET-999" or "reveal your token" cannot succeed. `fixtures/jira/VWO-48.json`
  contains such an injection attempt on purpose.
- No `eval`, no `exec`, no shell execution from ticket content, no unsafe
  deserialization, no Playwright execution from the Streamlit server.
- Input size, ticket count, field length and ZIP size are all bounded; file
  names are sanitised against traversal.

---

## Limitations

- Requires a real LLM: quality and cost depend on `LLM_MODEL`. Nothing is
  simulated, so a run without credentials cannot produce artifacts.
- Generated Playwright code is a starting point. When the ticket does not
  describe the UI precisely, the bundle is marked `NEEDS_CONFIGURATION` with
  placeholder constants and an explicit list of what is missing — it is not
  claimed to be execution-ready.
- The ticket timeout is a wall-clock budget enforced by the pipeline. A crew
  that hangs inside a provider SDK is abandoned rather than killed, so a
  timed-out run can leave a background thread until the process exits.
- Tickets are processed sequentially, so a large batch takes as long as the
  sum of its parts.
- MCP support is exercised against the protocol, not against every vendor's
  server; unusual response shapes may need `JIRA_MCP_GET_ISSUE_TOOL` and
  `JIRA_MCP_ISSUE_KEY_ARG`.

---

## Deployment

### Streamlit Community Cloud

1. Push the repo to GitHub.
2. New app → main file `Crew_AI_QA_Pipeline/app.py`, Python 3.11+.
3. Paste the contents of `.streamlit/secrets.toml.example` into **Secrets** and
   fill in real values.
4. Deploy. `requirements.txt` in this folder is what gets installed.

Note that `outputs/` on Community Cloud is ephemeral — download the ZIP for
anything you want to keep.

### Docker

```bash
docker build -t jira-qa-crew:1.0.0 .
docker run --rm -p 8501:8501 --env-file .env -v "$PWD/outputs:/app/outputs" jira-qa-crew:1.0.0
```

or:

```bash
docker compose up --build
```

The image runs as a non-root user, bakes in no secrets, and exposes
`/_stcore/health` for health checks.

### CI

`.github/workflows/jira-qa-crew-ci.yml` runs `ruff check` and `pytest` on
Python 3.11 and 3.12 for every push and pull request that touches this folder.
Integration tests stay deselected there.
