# Requirements Clarifier Agent
#
# Analyzes a Jira user story to catch requirement problems *before* they
# become expensive defects:
#   - ambiguous / vague language ("fast", "user-friendly", "appropriate")
#   - missing or non-testable acceptance criteria
#   - undefined error handling and edge cases
#   - INVEST violations (Independent, Negotiable, Valuable, Estimable,
#     Small, Testable)
#
# Multi-agent workflow (sequential):
#   1. Requirements Analyst        - pulls the story from Jira, audits it
#   2. Clarification Specialist    - turns each gap into a targeted question
#   3. Acceptance Criteria Author  - rewrites AC as testable Given/When/Then
#                                    and assembles the final report
#
# Usage:
#   python 02_Requirements_Clarifier_Agent.py                 # defaults to SHOP-1
#   python 02_Requirements_Clarifier_Agent.py --issue SHOP-7
#   python 02_Requirements_Clarifier_Agent.py --issue SHOP-7 --post
#
# .env (in this folder) must contain:
#   GROQ_API_KEY, GROQ_MODEL, GROQ_BASE_URL   (already used by the other agents)
#   JIRA_BASE_URL   e.g. https://eqetesting.atlassian.net
#   JIRA_EMAIL      your Atlassian account email
#   JIRA_API_TOKEN  from https://id.atlassian.com/manage-profile/security/api-tokens

from crewai import Agent, Task, Crew, Process
from crewai import LLM
from crewai.tools import tool
from dotenv import load_dotenv
import argparse
import os
import sys

import requests
from requests.auth import HTTPBasicAuth

# Windows consoles default to cp1252, which can't print the Unicode
# punctuation crewai's verbose logs and LLM output use - force UTF-8.
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

load_dotenv()

groq_llm = LLM(
    model=f"openai/{os.getenv('GROQ_MODEL')}",
    api_key=os.getenv("GROQ_API_KEY"),
    base_url=os.getenv("GROQ_BASE_URL"),
)

JIRA_BASE_URL = (os.getenv("JIRA_BASE_URL") or "").rstrip("/")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")


# ── Jira REST helpers ──────────────────────────────────────────────────
def _jira_auth() -> HTTPBasicAuth:
    if not (JIRA_BASE_URL and JIRA_EMAIL and JIRA_API_TOKEN):
        raise RuntimeError(
            "Missing Jira config. Set JIRA_BASE_URL, JIRA_EMAIL and "
            "JIRA_API_TOKEN in CrewAI/.env"
        )
    return HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN)


def _adf_to_text(node) -> str:
    """Flatten an Atlassian Document Format node tree into plain text."""
    if node is None:
        return ""
    if isinstance(node, list):
        return "".join(_adf_to_text(n) for n in node)
    if isinstance(node, dict):
        ntype = node.get("type")
        if ntype == "text":
            return node.get("text", "")
        if ntype == "hardBreak":
            return "\n"
        inner = _adf_to_text(node.get("content"))
        if ntype in ("paragraph", "heading"):
            return inner + "\n"
        if ntype == "listItem":
            return "- " + inner
        return inner
    return ""


def fetch_story(issue_key: str) -> str:
    """Return a readable summary + description + acceptance criteria for a Jira issue."""
    url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}"
    resp = requests.get(
        url,
        auth=_jira_auth(),
        headers={"Accept": "application/json"},
        params={"fields": "summary,description,issuetype,status,priority,labels"},
        timeout=30,
    )
    resp.raise_for_status()
    f = resp.json().get("fields", {})
    description = _adf_to_text(f.get("description")).strip() or "(no description)"
    return (
        f"Issue: {issue_key}\n"
        f"Type: {f.get('issuetype', {}).get('name', '?')}   "
        f"Status: {f.get('status', {}).get('name', '?')}   "
        f"Priority: {f.get('priority', {}).get('name', '?')}\n"
        f"Summary: {f.get('summary', '')}\n\n"
        f"Description / Acceptance Criteria:\n{description}"
    )


def post_comment(issue_key: str, body: str) -> str:
    url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}/comment"
    payload = {
        "body": {
            "type": "doc",
            "version": 1,
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": body}]}
            ],
        }
    }
    resp = requests.post(url, auth=_jira_auth(), json=payload, timeout=30)
    resp.raise_for_status()
    return f"Comment posted to {issue_key} (id {resp.json().get('id')})"


# ── Tool exposed to the agent ─────────────────────────────────────────
@tool("Fetch Jira Story")
def fetch_jira_story(issue_key: str) -> str:
    """Fetch a Jira issue's summary, description and acceptance criteria as plain text.
    Pass the issue key, e.g. 'SHOP-1'."""
    return fetch_story(issue_key)


# ── Vague terms the analyst must flag ─────────────────────────────────
VAGUE_TERMS = (
    "fast, quick, slow, responsive, appropriate, adequate, sufficient, "
    "user-friendly, intuitive, easy, simple, seamless, robust, secure, "
    "scalable, flexible, efficient, optimized, reasonable, acceptable, "
    "several, some, many, few, most, minimal, etc., and/or, as needed, "
    "if required, where applicable, handle gracefully, properly, correctly, "
    "better, improved, modern, clean, nice"
)


# ── Agent 1: Requirements Analyst ─────────────────────────────────────
requirements_analyst = Agent(
    role="Senior Requirements Analyst (QA)",
    goal=(
        "Pull the user story from Jira and audit it for ambiguity, missing "
        "acceptance criteria, undefined error handling, missing edge cases, "
        "and INVEST / testability violations."
    ),
    backstory=(
        "You are a QA lead with 15+ years shifting testing left. You have "
        "reviewed thousands of user stories and know that the costly defects "
        "trace back to a single vague sentence nobody questioned in refinement. "
        "You are relentless about measurable, testable outcomes."
    ),
    llm=groq_llm,
    tools=[fetch_jira_story],
    verbose=True,
    allow_delegation=False,
)

# ── Agent 2: Clarification Specialist ─────────────────────────────────
clarification_specialist = Agent(
    role="Requirements Clarification Specialist",
    goal=(
        "Convert every gap and ambiguity found by the analyst into a specific, "
        "answerable clarification question aimed at the product owner."
    ),
    backstory=(
        "You facilitate backlog refinement for a living. Your questions are "
        "sharp and closed enough to get a decision in one sentence - never "
        "'can you clarify?', always 'when the password fails complexity rules, "
        "should the form show errors inline per-rule or a single summary?'."
    ),
    llm=groq_llm,
    verbose=True,
    allow_delegation=False,
)

# ── Agent 3: Acceptance Criteria Author ───────────────────────────────
acceptance_criteria_author = Agent(
    role="Acceptance Criteria Author",
    goal=(
        "Rewrite the story's acceptance criteria as testable, measurable "
        "Given/When/Then scenarios and assemble the final clarification report."
    ),
    backstory=(
        "You are a business analyst who writes acceptance criteria developers "
        "and testers never argue about: each one has concrete inputs, an "
        "observable result, and a number where a number belongs."
    ),
    llm=groq_llm,
    verbose=True,
    allow_delegation=False,
)

# ── Task 1: Audit the story ───────────────────────────────────────────
analysis_task = Task(
    description=(
        """Use the 'Fetch Jira Story' tool with issue key '{issue_key}' to load the story.
Then produce a structured audit.

Flag EVERY occurrence of vague, unmeasurable language. Treat these terms as
red flags (non-exhaustive): {vague_terms}

Your audit MUST have these sections:
1. **Story Restatement** - the story and its current acceptance criteria, verbatim.
2. **INVEST Assessment** - rate each of Independent, Negotiable, Valuable,
   Estimable, Small, Testable as PASS / WEAK / FAIL with a one-line reason.
3. **Ambiguities** - table of: quoted phrase | why it is ambiguous | impact if left as-is.
4. **Missing Acceptance Criteria** - scenarios with no criterion at all.
5. **Undefined Error Handling** - failure paths the story is silent on.
6. **Missing Edge Cases** - boundaries, limits, concurrency, data variations.
7. **Testability Gaps** - anything that cannot be verified objectively as written.

Be specific to THIS story. Do not invent requirements - name what is missing,
do not decide it.
"""
    ),
    expected_output=(
        "A markdown audit with the 7 numbered sections. Ambiguities and "
        "Missing AC presented as tables. No filler."
    ),
    agent=requirements_analyst,
)

# ── Task 2: Generate clarification questions ──────────────────────────
clarification_task = Task(
    description=(
        """Using the analyst's audit, generate targeted clarification questions.

Rules:
- One question per distinct gap or ambiguity.
- Each question must be answerable in 1-2 sentences by a product owner.
- Offer options when the answer space is small
  (e.g. "inline per-field or a single summary banner?").
- Group under headings: Ambiguities, Missing Criteria, Error Handling, Edge Cases.
- Number questions continuously (Q1, Q2, ...).
- After each question add "-> Suggested default:" with a sensible assumption
  the team can adopt if the PO does not respond.
"""
    ),
    expected_output=(
        "A numbered, grouped list of clarification questions, each with a "
        "suggested default answer."
    ),
    agent=clarification_specialist,
)

# ── Task 3: Rewrite AC + assemble report ──────────────────────────────
rewrite_task = Task(
    description=(
        """Produce the final Requirements Clarification Report in clean markdown.

Sections, in order:
1. **Story** - key {issue_key}, summary, and the original story text.
2. **Verdict** - READY / NEEDS CLARIFICATION / NOT READY, plus a one-paragraph
   rationale and a risk level (Low / Medium / High / Critical).
3. **Findings Summary** - the analyst's audit, tightened (keep the tables).
4. **Clarification Questions** - from the clarification specialist, unchanged.
5. **Proposed Acceptance Criteria** - rewrite EVERY criterion (and add the
   missing ones) as Given/When/Then scenarios. Each must have concrete inputs,
   an observable outcome, and explicit numbers/limits. Mark additions with
   "(NEW)" and assumptions with "(ASSUMPTION - confirm via Qn)".
6. **Definition of Ready Checklist** - tick/cross list for this story.

Keep it copy-paste ready for a Jira comment.
"""
    ),
    expected_output=(
        "A complete markdown report with all 6 sections, ready to paste into Jira."
    ),
    agent=acceptance_criteria_author,
    output_file="requirements_clarification_output.md",
)

crew = Crew(
    agents=[requirements_analyst, clarification_specialist, acceptance_criteria_author],
    tasks=[analysis_task, clarification_task, rewrite_task],
    process=Process.sequential,
    verbose=True,
)


# ── Entry point ──────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clarify a Jira user story.")
    parser.add_argument(
        "--issue", default="SHOP-1", help="Jira issue key (default: SHOP-1)"
    )
    parser.add_argument(
        "--post",
        action="store_true",
        help="Post the report back to the Jira issue as a comment",
    )
    args = parser.parse_args()

    inputs = {
        "issue_key": args.issue,
        "vague_terms": VAGUE_TERMS,
    }

    result = crew.kickoff(inputs=inputs)

    print("\n" + "=" * 60)
    print(f"REQUIREMENTS CLARIFICATION REPORT - {args.issue}")
    print("=" * 60)
    print(result)

    from datetime import datetime

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    copy_path = f"requirements_clarification_{args.issue}_{ts}.md"
    with open(copy_path, "w", encoding="utf-8") as fh:
        fh.write(str(result))
    print(f"\nSaved to: {copy_path}")

    if args.post:
        try:
            print(post_comment(args.issue, str(result)))
        except Exception as exc:  # noqa: BLE001 - surface any Jira error to the user
            print(f"Failed to post comment: {exc}")
