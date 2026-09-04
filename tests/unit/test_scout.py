import pytest

from oss_agent.agents.mock_runner import MockAgentRunner
from oss_agent.config.profile import DEFAULT_PROFILE
from oss_agent.domain.enums import WorkflowState
from oss_agent.domain.models import WorkflowSnapshot
from oss_agent.persistence.repository import InMemoryWorkflowRepository
from oss_agent.scoring.engine import ScoringEngine
from oss_agent.scout.models import OpportunityStatus
from oss_agent.scout.service import ScoutService
from oss_agent.scout.store import InMemoryOpportunityRepository

from tests.conftest import FULL_NAME, ISSUE_NUMBER

pytestmark = pytest.mark.unit


def _scout(seeded_github, workflows=None, store=None):
    return ScoutService(
        github=seeded_github, runner=MockAgentRunner(), scoring=ScoringEngine(),
        profile=DEFAULT_PROFILE, workflows=workflows or InMemoryWorkflowRepository(),
        store=store or InMemoryOpportunityRepository(),
    )


def test_scan_queues_a_scored_opportunity(seeded_github):
    store = InMemoryOpportunityRepository()
    scout = _scout(seeded_github, store=store)
    result = scout.scan(query='label:"good first issue"', min_score=0)

    assert result.scanned >= 1
    assert result.stored >= 1
    queued = store.list()
    assert any(o.repository_full_name == FULL_NAME and o.issue_number == ISSUE_NUMBER for o in queued)
    opp = store.get(f"{FULL_NAME}#{ISSUE_NUMBER}")
    assert 0 <= opp.score <= 100
    assert opp.status is OpportunityStatus.NEW
    assert opp.reasons  # explains the score


def test_low_score_is_not_queued(seeded_github):
    store = InMemoryOpportunityRepository()
    scout = _scout(seeded_github, store=store)
    result = scout.scan(query='label:"good first issue"', min_score=99.0)
    assert result.stored == 0
    assert result.skipped_low_score >= 1


def test_dismissed_opportunity_is_not_requeued(seeded_github):
    store = InMemoryOpportunityRepository()
    scout = _scout(seeded_github, store=store)
    scout.scan(query='label:"good first issue"', min_score=0)
    key = f"{FULL_NAME}#{ISSUE_NUMBER}"
    store.set_status(key, OpportunityStatus.DISMISSED)

    result = scout.scan(query='label:"good first issue"', min_score=0)
    assert result.skipped_duplicate >= 1
    assert store.get(key).status is OpportunityStatus.DISMISSED


def test_active_workflow_blocks_duplicate(seeded_github):
    workflows = InMemoryWorkflowRepository()
    workflows.save(WorkflowSnapshot(id="w1", repository_full_name=FULL_NAME,
                                    issue_number=ISSUE_NUMBER, state=WorkflowState.PLANNING))
    scout = _scout(seeded_github, workflows=workflows)
    result = scout.scan(query='label:"good first issue"', min_score=0)
    assert result.skipped_duplicate >= 1
    assert result.stored == 0


def test_existing_open_pr_blocks_duplicate(seeded_github):
    # Someone already has an open PR fixing this issue -> the scout must skip it.
    seeded_github.add_linked_pr(FULL_NAME, ISSUE_NUMBER)
    scout = _scout(seeded_github)
    result = scout.scan(query='label:"good first issue"', min_score=0)
    assert result.skipped_duplicate >= 1
    assert result.stored == 0


def test_difficulty_filter_keeps_matching(seeded_github):
    from oss_agent.domain.enums import Difficulty

    store = InMemoryOpportunityRepository()
    scout = _scout(seeded_github, store=store)
    # The seeded "good first issue" is analyzed as EASY.
    result = scout.scan(query='label:"good first issue"', min_score=0, difficulty=Difficulty.EASY)
    assert result.stored >= 1


def test_difficulty_filter_excludes_non_matching(seeded_github):
    from oss_agent.domain.enums import Difficulty

    store = InMemoryOpportunityRepository()
    scout = _scout(seeded_github, store=store)
    result = scout.scan(query='label:"good first issue"', min_score=0, difficulty=Difficulty.HARD)
    assert result.stored == 0
    assert result.skipped_filtered >= 1


def test_run_forever_is_bounded_and_resilient(seeded_github):
    scout = _scout(seeded_github)
    cycles = []
    results = scout.run_forever(
        interval_seconds=0.0, max_cycles=3, min_score=0, query='label:"good first issue"',
        on_cycle=lambda r: cycles.append(r), sleep=lambda s: None,
    )
    assert len(results) == 3
    assert len(cycles) == 3
    assert all(r.cycle == i + 1 for i, r in enumerate(results))


def test_queue_is_ranked_by_score():
    store = InMemoryOpportunityRepository()
    from oss_agent.scout.models import Opportunity

    store.upsert(Opportunity(repository_full_name="a/b", issue_number=1, score=40))
    store.upsert(Opportunity(repository_full_name="a/b", issue_number=2, score=80))
    store.upsert(Opportunity(repository_full_name="a/b", issue_number=3, score=60))
    scores = [o.score for o in store.list()]
    assert scores == [80, 60, 40]
