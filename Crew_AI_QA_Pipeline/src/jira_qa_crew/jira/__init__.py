"""Jira integration: providers, deterministic gateway and ADF handling."""

from jira_qa_crew.jira.base import JiraProvider
from jira_qa_crew.jira.demo_provider import JiraDemoProvider
from jira_qa_crew.jira.gateway import FetchAttempt, FetchOutcome, JiraGateway
from jira_qa_crew.jira.mcp_provider import JiraMCPProvider
from jira_qa_crew.jira.rest_provider import JiraRestProvider

__all__ = [
    "FetchAttempt",
    "FetchOutcome",
    "JiraDemoProvider",
    "JiraGateway",
    "JiraMCPProvider",
    "JiraProvider",
    "JiraRestProvider",
]
