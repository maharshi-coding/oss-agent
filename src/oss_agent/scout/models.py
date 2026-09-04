"""Scout domain models: a scored contribution opportunity and a scan result."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from oss_agent.domain.enums import ContributionType, Difficulty, Recommendation
from oss_agent.domain.models import utcnow


class OpportunityStatus(str, Enum):
    """Lifecycle of a queued opportunity. Only a human moves it past NEW."""

    NEW = "new"                # freshly scouted, awaiting review
    DISMISSED = "dismissed"    # human rejected it (never re-queue)
    PROMOTED = "promoted"      # a workflow was created for it
    CONTRIBUTED = "contributed"  # a PR was opened for it


class Opportunity(BaseModel):
    model_config = ConfigDict(use_enum_values=False)

    repository_full_name: str
    issue_number: int = Field(ge=1)
    title: str = ""
    url: Optional[str] = None
    contribution_type: ContributionType = ContributionType.BUG_FIX
    difficulty: Difficulty = Difficulty.MODERATE
    score: float = Field(default=0.0, ge=0.0, le=100.0)
    recommendation: Recommendation = Recommendation.SKIP
    summary: str = ""
    reasons: list[str] = Field(default_factory=list)
    status: OpportunityStatus = OpportunityStatus.NEW
    discovered_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    @property
    def key(self) -> str:
        return f"{self.repository_full_name}#{self.issue_number}"


class ScanResult(BaseModel):
    cycle: int = 0
    at: datetime = Field(default_factory=utcnow)
    query: str = ""
    scanned: int = 0
    stored: int = 0
    skipped_duplicate: int = 0
    skipped_low_score: int = 0
    skipped_filtered: int = 0
    errors: list[str] = Field(default_factory=list)
    top: list[Opportunity] = Field(default_factory=list)

    @property
    def summary(self) -> str:
        filtered = f" / {self.skipped_filtered} filtered" if self.skipped_filtered else ""
        return (
            f"cycle {self.cycle}: scanned {self.scanned}, queued {self.stored}, "
            f"skipped {self.skipped_duplicate} dup / {self.skipped_low_score} low-score"
            + filtered
            + (f", {len(self.errors)} error(s)" if self.errors else "")
        )
