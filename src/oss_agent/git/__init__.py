"""Git abstraction: the only place that shells out to git."""

from oss_agent.git.naming import branch_name_for
from oss_agent.git.service import (
    GitError,
    GitService,
    SecretDetectedError,
    WorktreeInfo,
)

__all__ = [
    "branch_name_for",
    "GitError",
    "GitService",
    "SecretDetectedError",
    "WorktreeInfo",
]
