"""Git safety policy.

Blocks the git operations that can destroy history or push to protected branches.
Used by :mod:`oss_agent.git.service` and the pre-push hook. Deterministic and
independent of agent reasoning.
"""

from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_PROTECTED = ("main", "master", "develop", "release")


class GitSafetyError(RuntimeError):
    """Raised when a git operation violates the safety policy."""


@dataclass(frozen=True)
class GitOpAssessment:
    allowed: bool
    reasons: list[str] = field(default_factory=list)

    def raise_if_blocked(self) -> None:
        if not self.allowed:
            raise GitSafetyError("; ".join(self.reasons) or "git operation blocked")


def _norm(branch: str) -> str:
    branch = branch.strip()
    for prefix in ("refs/heads/", "origin/", "heads/"):
        if branch.startswith(prefix):
            branch = branch[len(prefix) :]
    return branch


def is_protected(branch: str, protected: tuple[str, ...] | list[str] = DEFAULT_PROTECTED) -> bool:
    name = _norm(branch)
    return name in {_norm(p) for p in protected}


def assess_push(
    branch: str,
    *,
    force: bool = False,
    protected: tuple[str, ...] | list[str] = DEFAULT_PROTECTED,
) -> GitOpAssessment:
    reasons: list[str] = []
    if is_protected(branch, protected):
        reasons.append(f"refusing to push to protected branch '{_norm(branch)}'")
    if force:
        reasons.append("force-push is not permitted")
    return GitOpAssessment(allowed=not reasons, reasons=reasons)


def assess_branch_delete(
    branch: str, *, protected: tuple[str, ...] | list[str] = DEFAULT_PROTECTED
) -> GitOpAssessment:
    if is_protected(branch, protected):
        return GitOpAssessment(False, [f"refusing to delete protected branch '{_norm(branch)}'"])
    return GitOpAssessment(True)


def assess_reset(
    *,
    hard: bool,
    current_branch: str,
    protected: tuple[str, ...] | list[str] = DEFAULT_PROTECTED,
) -> GitOpAssessment:
    if hard and is_protected(current_branch, protected):
        return GitOpAssessment(
            False,
            [f"refusing hard reset on protected branch '{_norm(current_branch)}'"],
        )
    return GitOpAssessment(True)


def assess_checkout_target(
    branch: str, *, protected: tuple[str, ...] | list[str] = DEFAULT_PROTECTED
) -> GitOpAssessment:
    """Implementation work must never target a protected branch for commits."""
    if is_protected(branch, protected):
        return GitOpAssessment(
            False, [f"implementation branch may not be protected branch '{_norm(branch)}'"]
        )
    return GitOpAssessment(True)
