"""SQLAlchemy ORM models for persisted workflow state.

The full :class:`~oss_agent.domain.models.WorkflowSnapshot` is stored as JSON in
the ``data`` column (the source of truth, so nothing about the aggregate is lost
on resume). A handful of denormalized, indexed columns make listing and duplicate
detection efficient and portable to PostgreSQL later.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class WorkflowRow(Base):
    __tablename__ = "workflows"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    state: Mapped[str] = mapped_column(String(32), index=True)
    repository_full_name: Mapped[str | None] = mapped_column(
        String(255), index=True, nullable=True
    )
    issue_number: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    # Full serialized WorkflowSnapshot (JSON-safe dict).
    data: Mapped[dict] = mapped_column(JSON)
