"""Strict bounded recovery from a live backend's schema-invalid reply."""

import json

import pytest
from pydantic import ValidationError

from oss_agent.agents.base import AgentError, BackendUnavailableError
from oss_agent.agents.claude_runner import BackendInvocation, ClaudeAgentRunner
from oss_agent.domain.enums import MaintainerVerdict
from oss_agent.domain.models import ImplementationPlan, MaintainerReview


def plan_payload():
    return {
        "repository_full_name": "owner/repo",
        "issue_number": 77,
        "objective": "Preserve configured quota identities",
        "branch_name": "fix/77-bug-fix",
    }


def test_schema_invalid_reply_is_retried_without_relaxing_contract(monkeypatch):
    runner = ClaudeAgentRunner()
    invalid = {**plan_payload(), "test_plan_note": None}
    replies = iter([invalid, plan_payload()])
    prompts = []

    def invoke(prompt, **kwargs):
        prompts.append(prompt)
        return BackendInvocation(json.dumps(next(replies)), 0, 0.1)

    monkeypatch.setattr(runner, "_invoke", invoke)
    result = runner._ask("planner", "Produce the plan", ImplementationPlan)

    assert result.objective == plan_payload()["objective"]
    assert len(prompts) == 2
    assert "test_plan_note" in prompts[1]
    assert "no undeclared keys" in prompts[1]
    with pytest.raises(ValidationError):
        ImplementationPlan.model_validate(invalid)


def test_second_schema_invalid_reply_still_fails(monkeypatch):
    runner = ClaudeAgentRunner()
    prompts = []

    def invoke(prompt, **kwargs):
        prompts.append(prompt)
        return BackendInvocation(json.dumps({**plan_payload(), "test_plan_note": None}), 0, 0.1)

    monkeypatch.setattr(runner, "_invoke", invoke)
    with pytest.raises(AgentError, match="response failed validation"):
        runner._ask("planner", "Produce the plan", ImplementationPlan)
    assert len(prompts) == 2


def test_malformed_json_gets_one_fresh_response(monkeypatch):
    runner = ClaudeAgentRunner()
    # The live failure omitted the final list delimiter, not a schema field.
    replies = iter(['{"verdict":"REQUEST_CHANGES","praise":["Evidence."}',
                    json.dumps({"verdict": "REJECT", "reasons": ["Still unsafe"]})])
    prompts = []

    def invoke(prompt, **kwargs):
        prompts.append(prompt)
        return BackendInvocation(next(replies), 0, 0.1)

    monkeypatch.setattr(runner, "_invoke", invoke)
    result = runner._ask("maintainer", "Review the change", MaintainerReview)
    assert result.verdict == MaintainerVerdict.REJECT
    assert result.reasons == ["Still unsafe"]
    assert len(prompts) == 2
    assert "invalid_json_object" in prompts[1]
    assert "SAME schema" in prompts[1]


def test_second_malformed_reply_still_fails(monkeypatch):
    runner = ClaudeAgentRunner()
    prompts = []

    def invoke(prompt, **kwargs):
        prompts.append(prompt)
        return BackendInvocation('{"verdict":"APPROVE","praise":["Evidence."}', 0, 0.1)

    monkeypatch.setattr(runner, "_invoke", invoke)
    with pytest.raises(AgentError, match="no JSON object found in MaintainerReview response"):
        runner._ask("maintainer", "Review the change", MaintainerReview)
    assert len(prompts) == 2


@pytest.mark.parametrize("error", [AgentError("execution failed"),
                                 BackendUnavailableError("not authenticated")])
def test_invocation_failure_is_not_a_structured_response_retry(monkeypatch, error):
    runner = ClaudeAgentRunner()
    prompts = []

    def invoke(prompt, **kwargs):
        prompts.append(prompt)
        raise error

    monkeypatch.setattr(runner, "_invoke", invoke)
    with pytest.raises(type(error), match=str(error)):
        runner._ask("planner", "Produce the plan", ImplementationPlan)
    assert len(prompts) == 1


def test_valid_request_changes_is_returned_without_retry(monkeypatch):
    runner = ClaudeAgentRunner()
    prompts = []

    def invoke(prompt, **kwargs):
        prompts.append(prompt)
        return BackendInvocation(json.dumps({"verdict": "REQUEST_CHANGES",
                                            "requested_changes": ["Add coverage"]}), 0, 0.1)

    monkeypatch.setattr(runner, "_invoke", invoke)
    result = runner._ask("maintainer", "Review the change", MaintainerReview)
    assert result.verdict == MaintainerVerdict.REQUEST_CHANGES
    assert len(prompts) == 1
