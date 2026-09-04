import pytest

from oss_agent.domain.enums import ContributionType, WorkflowState
from oss_agent.domain.models import (
    ContributionScore,
    Repository,
    ScoreComponent,
    WorkflowSnapshot,
)
from oss_agent.git.naming import branch_name_for
from oss_agent.persistence.database import in_memory_database
from oss_agent.persistence.repository import (
    InMemoryWorkflowRepository,
    SqlAlchemyWorkflowRepository,
)

pytestmark = pytest.mark.unit


def test_repository_full_name_and_validation():
    r = Repository(owner="octocat", name="hello")
    assert r.full_name == "octocat/hello"
    with pytest.raises(Exception):
        Repository(owner="bad/owner", name="x")


def test_branch_naming_is_deterministic():
    assert branch_name_for(123, ContributionType.BUG_FIX) == "fix/issue-123"
    assert branch_name_for(456, ContributionType.FEATURE) == "feature/issue-456"
    assert branch_name_for(7, ContributionType.DOCUMENTATION) == "docs/issue-7"
    assert branch_name_for(7) == branch_name_for(7)  # stable


def test_snapshot_json_roundtrip_preserves_nested_artifacts():
    snap = WorkflowSnapshot(id="w1", repository_full_name="o/r", issue_number=5)
    snap.score = ContributionScore(
        repository_full_name="o/r", issue_number=5, overall=80, base_score=85,
        components=[ScoreComponent(dimension="skill_match", raw=0.9, weight=0.1, weighted=0.09)],
        recommendation="PURSUE",
    )
    data = snap.model_dump(mode="json")
    restored = WorkflowSnapshot.model_validate(data)
    assert restored.score.overall == 80
    assert restored.score.components[0].dimension == "skill_match"


@pytest.mark.parametrize("make_repo", [
    lambda: InMemoryWorkflowRepository(),
    lambda: SqlAlchemyWorkflowRepository(in_memory_database()),
])
def test_repository_crud_and_queries(make_repo):
    repo = make_repo()
    snap = WorkflowSnapshot(id="w1", repository_full_name="o/r", issue_number=42)
    repo.save(snap)

    assert repo.exists("w1")
    assert repo.get("w1").issue_number == 42
    assert repo.find_by_issue("o/r", 42).id == "w1"
    assert repo.find_by_issue("o/r", 99) is None

    snap.state = WorkflowState.SCORING
    repo.save(snap)
    assert [s.id for s in repo.list(state=WorkflowState.SCORING)] == ["w1"]
    assert repo.list(state=WorkflowState.MERGED) == []

    assert repo.delete("w1")
    assert not repo.exists("w1")
    assert not repo.delete("w1")


def test_repository_survives_reload_same_database():
    db = in_memory_database()
    repo = SqlAlchemyWorkflowRepository(db)
    repo.save(WorkflowSnapshot(id="persist", repository_full_name="o/r", issue_number=1))
    # A brand-new repository object over the same DB still sees the workflow
    # (simulates a process restart / resume).
    repo2 = SqlAlchemyWorkflowRepository(db)
    assert repo2.get("persist") is not None


# The snapshot is persisted as a JSON blob, so new *optional* fields are a
# backwards-compatible schema change: a row written by an older version (whose
# JSON lacks the newer keys) must still deserialize, with the new fields taking
# their defaults. These are the fields added during the refactor.
_NEW_FIELDS = ["suitability", "attempts", "learning_report",
               "human_approved", "human_decision_note"]


def test_old_snapshot_without_new_fields_still_loads():
    snap = WorkflowSnapshot(id="legacy", repository_full_name="o/r", issue_number=7)
    data = snap.model_dump(mode="json")
    # Simulate a row written before the refactor existed.
    for key in _NEW_FIELDS:
        data.pop(key, None)

    restored = WorkflowSnapshot.model_validate(data)
    assert restored.id == "legacy"
    assert restored.suitability is None
    assert restored.attempts == []
    assert restored.learning_report is None
    assert restored.human_approved is False
    assert restored.human_decision_note is None


def test_old_row_deserializes_through_the_sql_store():
    from oss_agent.persistence.orm import WorkflowRow

    db = in_memory_database()
    repo = SqlAlchemyWorkflowRepository(db)
    snap = WorkflowSnapshot(id="legacy2", repository_full_name="o/r", issue_number=8)
    data = snap.model_dump(mode="json")
    for key in _NEW_FIELDS:
        data.pop(key, None)
    # Insert a legacy-shaped row directly (bypassing the current serializer).
    with db.session() as session:
        session.add(WorkflowRow(
            id="legacy2", state=snap.state.value, repository_full_name="o/r",
            issue_number=8, created_at=snap.created_at, updated_at=snap.updated_at,
            data=data,
        ))
        session.commit()
    loaded = repo.get("legacy2")
    assert loaded is not None
    assert loaded.attempts == [] and loaded.human_approved is False
