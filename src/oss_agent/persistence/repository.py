"""Workflow repository: the persistence boundary for workflow state.

The orchestrator depends only on the :class:`WorkflowRepository` protocol, never
on SQLAlchemy directly. Two implementations are provided: a SQLite-backed one for
real use and an in-memory one for tests. A PostgreSQL implementation can be added
later by swapping the ``Database`` URL — no interface change required.
"""

from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from oss_agent.domain.enums import WorkflowState
from oss_agent.domain.models import WorkflowSnapshot
from oss_agent.persistence.database import Database
from oss_agent.persistence.orm import WorkflowRow


@runtime_checkable
class WorkflowRepository(Protocol):
    """Persistence contract for workflow snapshots (idempotent upsert semantics)."""

    def save(self, snapshot: WorkflowSnapshot) -> None: ...
    def get(self, workflow_id: str) -> Optional[WorkflowSnapshot]: ...
    def exists(self, workflow_id: str) -> bool: ...
    def delete(self, workflow_id: str) -> bool: ...
    def list(self, *, state: Optional[WorkflowState] = None) -> list[WorkflowSnapshot]: ...
    def find_by_issue(
        self, repository_full_name: str, issue_number: int
    ) -> Optional[WorkflowSnapshot]: ...


def _to_row(snapshot: WorkflowSnapshot) -> dict:
    data = snapshot.model_dump(mode="json")
    return {
        "id": snapshot.id,
        "state": snapshot.state.value,
        "repository_full_name": snapshot.repository_full_name,
        "issue_number": snapshot.issue_number,
        "created_at": snapshot.created_at,
        "updated_at": snapshot.updated_at,
        "data": data,
    }


class SqlAlchemyWorkflowRepository:
    """SQLite/PostgreSQL-backed repository."""

    def __init__(self, database: Database) -> None:
        self._db = database

    def save(self, snapshot: WorkflowSnapshot) -> None:
        snapshot.touch()
        payload = _to_row(snapshot)
        with self._db.session() as session:
            row = session.get(WorkflowRow, snapshot.id)
            if row is None:
                row = WorkflowRow(id=snapshot.id)
                session.add(row)
            row.state = payload["state"]
            row.repository_full_name = payload["repository_full_name"]
            row.issue_number = payload["issue_number"]
            row.created_at = payload["created_at"]
            row.updated_at = payload["updated_at"]
            row.data = payload["data"]
            session.commit()

    def get(self, workflow_id: str) -> Optional[WorkflowSnapshot]:
        with self._db.session() as session:
            row = session.get(WorkflowRow, workflow_id)
            if row is None:
                return None
            return WorkflowSnapshot.model_validate(row.data)

    def exists(self, workflow_id: str) -> bool:
        with self._db.session() as session:
            return session.get(WorkflowRow, workflow_id) is not None

    def delete(self, workflow_id: str) -> bool:
        with self._db.session() as session:
            row = session.get(WorkflowRow, workflow_id)
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True

    def list(self, *, state: Optional[WorkflowState] = None) -> list[WorkflowSnapshot]:
        from sqlalchemy import select

        with self._db.session() as session:
            stmt = select(WorkflowRow).order_by(WorkflowRow.updated_at.desc())
            if state is not None:
                stmt = stmt.where(WorkflowRow.state == state.value)
            rows = session.execute(stmt).scalars().all()
            return [WorkflowSnapshot.model_validate(r.data) for r in rows]

    def find_by_issue(
        self, repository_full_name: str, issue_number: int
    ) -> Optional[WorkflowSnapshot]:
        from sqlalchemy import select

        with self._db.session() as session:
            stmt = (
                select(WorkflowRow)
                .where(WorkflowRow.repository_full_name == repository_full_name)
                .where(WorkflowRow.issue_number == issue_number)
                .order_by(WorkflowRow.updated_at.desc())
            )
            row = session.execute(stmt).scalars().first()
            return WorkflowSnapshot.model_validate(row.data) if row else None


class InMemoryWorkflowRepository:
    """Dict-backed repository for tests. Stores deep copies to mimic a real store."""

    def __init__(self) -> None:
        self._store: dict[str, dict] = {}

    def save(self, snapshot: WorkflowSnapshot) -> None:
        snapshot.touch()
        self._store[snapshot.id] = snapshot.model_dump(mode="json")

    def get(self, workflow_id: str) -> Optional[WorkflowSnapshot]:
        data = self._store.get(workflow_id)
        return WorkflowSnapshot.model_validate(data) if data else None

    def exists(self, workflow_id: str) -> bool:
        return workflow_id in self._store

    def delete(self, workflow_id: str) -> bool:
        return self._store.pop(workflow_id, None) is not None

    def list(self, *, state: Optional[WorkflowState] = None) -> list[WorkflowSnapshot]:
        snapshots = [WorkflowSnapshot.model_validate(d) for d in self._store.values()]
        if state is not None:
            snapshots = [s for s in snapshots if s.state == state]
        return sorted(snapshots, key=lambda s: s.updated_at, reverse=True)

    def find_by_issue(
        self, repository_full_name: str, issue_number: int
    ) -> Optional[WorkflowSnapshot]:
        matches = [
            s
            for s in self.list()
            if s.repository_full_name == repository_full_name
            and s.issue_number == issue_number
        ]
        return matches[0] if matches else None
