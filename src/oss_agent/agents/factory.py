"""Factory selecting the agent runner from configuration."""

from __future__ import annotations

from typing import Optional

from oss_agent.agents.base import AgentRunner
from oss_agent.agents.claude_runner import ClaudeAgentRunner
from oss_agent.agents.mock_runner import MockAgentRunner, Solution
from oss_agent.config.settings import AgentBackend, Settings, get_settings
from oss_agent.observability.logging import get_logger

logger = get_logger("agents.factory")


def create_agent_runner(
    settings: Optional[Settings] = None,
    *,
    solution: Optional[Solution] = None,
) -> AgentRunner:
    settings = settings or get_settings()
    if settings.agent_backend is AgentBackend.CLAUDE:
        logger.info("using Claude Code agent backend")
        return ClaudeAgentRunner(claude_bin=settings.claude_bin)
    logger.info("using deterministic mock agent backend")
    return MockAgentRunner(solution=solution)
