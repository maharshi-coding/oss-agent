"""Persistence for scouted opportunities (the review queue).

Mirrors the workflow repository pattern: a Protocol plus a SQLite-backed and an
in-memory implementation. Shares the same :class:`Database` as workflow state.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Protocol, runtime_checkable

from sqlalchemy import JSON, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from oss_agent.persistence.database import Database
from oss_agent.persistence.orm import Base
from oss_agent.scout.models import Opportunity, OpportunityStatus


class OpportunityRow(Base):
    __tablename__ = "opportunities"

    key: Mapped[str] = mapped_column(String(320), primary_key=True)  # repo#issue
    repository_full_name: Mapped[str] = mapped_column(String(255), index=True)
    issue_number: Mapped[int] = mapped_column(Integer, index=True)
    score: Mapped[float] = mapped_column(Float, index=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    data: Mapped[dict] = mapped_column(JSON)


@runtime_checkable
class OpportunityRepository(Protocol):
    def upsert(self, opp: Opportunity) -> None: ...
    def get(self, key: str) -> Optional[Opportunity]: ...
    def set_status(self, key: str, status: OpportunityStatus) -> bool: ...
    def list(
        self, *, status: Optional[OpportunityStatus] = None, limit: int = 50
    ) -> list[Opportunity]: ...


def _to_payload(opp: Opportunity) -> dict:
    return {
        "key": opp.key,
        "repository_full_name": opp.repository_full_name,
        "issue_number": opp.issue_number,
        "score": opp.score,
        "status": opp.status.value,
        "updated_at": opp.updated_at,
        "data": opp.model_dump(mode="json"),
    }


class SqlAlchemyOpportunityRepository:
    def __init__(self, database: Database) -> None:
        self._db = database
        self._db.create_all()  # ensure the opportunities table exists

    def upsert(self, opp: Opportunity) -> None:
        opp.updated_at = datetime.now(opp.updated_at.tzinfo)
        p = _to_payload(opp)
        with self._db.session() as s:
            row = s.get(OpportunityRow, opp.key)
            if row is None:
                row = OpportunityRow(key=opp.key)
                s.add(row)
            row.repository_full_name = p["repository_full_name"]
            row.issue_number = p["issue_number"]
            row.score = p["score"]
            row.status = p["status"]
            row.updated_at = p["updated_at"]
            row.data = p["data"]
            s.commit()

    def get(self, key: str) -> Optional[Opportunity]:
        with self._db.session() as s:
            row = s.get(OpportunityRow, key)
            return Opportunity.model_validate(row.data) if row else None

    def set_status(self, key: str, status: OpportunityStatus) -> bool:
        with self._db.session() as s:
            row = s.get(OpportunityRow, key)
            if row is None:
                return False
            data = dict(row.data)
            data["status"] = status.value
            row.data = data
            row.status = status.value
            s.commit()
            return True

    def list(
        self, *, status: Optional[OpportunityStatus] = None, limit: int = 50
    ) -> list[Opportunity]:
        from sqlalchemy import select

        with self._db.session() as s:
            stmt = select(OpportunityRow).order_by(OpportunityRow.score.desc())
            if status is not None:
                stmt = stmt.where(OpportunityRow.status == status.value)
            rows = s.execute(stmt.limit(limit)).scalars().all()
            return [Opportunity.model_validate(r.data) for r in rows]


class InMemoryOpportunityRepository:
    def __init__(self) -> None:
        self._store: dict[str, dict] = {}

    def upsert(self, opp: Opportunity) -> None:
        self._store[opp.key] = opp.model_dump(mode="json")

    def get(self, key: str) -> Optional[Opportunity]:
        d = self._store.get(key)
        return Opportunity.model_validate(d) if d else None

    def set_status(self, key: str, status: OpportunityStatus) -> bool:
        d = self._store.get(key)
        if d is None:
            return False
        d["status"] = status.value
        return True

    def list(
        self, *, status: Optional[OpportunityStatus] = None, limit: int = 50
    ) -> list[Opportunity]:
        opps = [Opportunity.model_validate(d) for d in self._store.values()]
        if status is not None:
            opps = [o for o in opps if o.status == status]
        return sorted(opps, key=lambda o: o.score, reverse=True)[:limit]
