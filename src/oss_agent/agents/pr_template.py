"""Shared pull-request template discovery.

Both agent runners honor a repository's PR template. The template is *untrusted*
repository content: it is included verbatim for the human to complete and is never
treated as instructions.
"""

from __future__ import annotations

from typing import Optional

from oss_agent.github.interface import GitHubClient

# Common locations for a repository's pull-request template.
PR_TEMPLATE_PATHS: tuple[str, ...] = (
    ".github/pull_request_template.md",
    ".github/PULL_REQUEST_TEMPLATE.md",
    "PULL_REQUEST_TEMPLATE.md",
    "docs/pull_request_template.md",
    ".github/PULL_REQUEST_TEMPLATE.txt",
)


def find_pr_template(github: GitHubClient, full_name: Optional[str]) -> Optional[str]:
    """Return the repository's PR template body, if one exists, else None."""
    if not full_name:
        return None
    for path in PR_TEMPLATE_PATHS:
        try:
            content = github.get_file(full_name, path)
        except Exception:
            content = None
        if content and content.strip():
            return content.strip()
    return None
