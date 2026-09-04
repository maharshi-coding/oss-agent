"""GitHub-specific DTOs that are not core domain entities.

Core entities (:class:`Repository`, :class:`Issue`) live in the domain layer and
are reused here. Pull requests, reviews, comments, and CI status are GitHub
concepts modeled separately so the domain layer stays platform-agnostic.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from oss_agent.domain.enums import ReviewVerdict


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore")


class PullRequest(_Base):
    number: int
    title: str
    body: str = ""
    state: str = "open"  # open | closed | merged
    head: str  # branch name
    base: str = "main"
    draft: bool = False
    merged: bool = False
    url: Optional[str] = None
    author: Optional[str] = None
    created_at: Optional[datetime] = None
    labels: list[str] = Field(default_factory=list)


class IssueComment(_Base):
    id: int
    author: Optional[str] = None
    body: str = ""
    created_at: Optional[datetime] = None


class ReviewComment(_Base):
    id: int
    author: Optional[str] = None
    body: str = ""
    path: Optional[str] = None
    line: Optional[int] = None
    created_at: Optional[datetime] = None


class Review(_Base):
    id: int
    author: Optional[str] = None
    state: ReviewVerdict = ReviewVerdict.REQUEST_CHANGES
    body: str = ""
    submitted_at: Optional[datetime] = None


class CheckRun(_Base):
    name: str
    status: str = "completed"  # queued | in_progress | completed
    conclusion: Optional[str] = None  # success | failure | neutral | cancelled | ...


class CIStatus(_Base):
    ref: str
    state: str = "pending"  # success | failure | pending | error
    checks: list[CheckRun] = Field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.state == "success"


class RepoFile(_Base):
    path: str
    is_dir: bool = False
