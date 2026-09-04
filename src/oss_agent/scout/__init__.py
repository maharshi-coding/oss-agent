"""Continuous opportunity scout: discover + score contribution candidates 24/7."""

from oss_agent.scout.models import Opportunity, OpportunityStatus, ScanResult
from oss_agent.scout.service import ScoutService
from oss_agent.scout.store import (
    InMemoryOpportunityRepository,
    OpportunityRepository,
    SqlAlchemyOpportunityRepository,
)

__all__ = [
    "Opportunity",
    "OpportunityStatus",
    "ScanResult",
    "ScoutService",
    "InMemoryOpportunityRepository",
    "OpportunityRepository",
    "SqlAlchemyOpportunityRepository",
]
