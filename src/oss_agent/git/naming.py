"""Deterministic branch naming.

Branch names are derived only from the contribution type and issue number, so a
resumed workflow always computes the same branch and can detect an existing one
(idempotency).
"""

from __future__ import annotations

from oss_agent.domain.enums import ContributionType

_PREFIX: dict[ContributionType, str] = {
    ContributionType.BUG_FIX: "fix",
    ContributionType.FEATURE: "feature",
    ContributionType.DOCUMENTATION: "docs",
    ContributionType.TEST: "test",
    ContributionType.REFACTOR: "refactor",
    ContributionType.PERFORMANCE: "perf",
    ContributionType.DEPENDENCY: "deps",
    ContributionType.CI: "ci",
    ContributionType.CHORE: "chore",
}


def branch_name_for(
    issue_number: int, contribution_type: ContributionType = ContributionType.BUG_FIX
) -> str:
    prefix = _PREFIX.get(contribution_type, "fix")
    return f"{prefix}/issue-{issue_number}"
