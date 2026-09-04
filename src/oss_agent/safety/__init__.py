"""Safety system: deterministic, defense-in-depth controls.

These modules never depend on the agent/LLM layer. They are consulted by the
execution engine, git service, GitHub adapters, orchestrator, and Claude hooks.
"""

from oss_agent.safety.commands import (
    CommandAssessment,
    Danger,
    assess_command,
    is_dangerous,
)
from oss_agent.safety.git_safety import (
    DEFAULT_PROTECTED,
    GitOpAssessment,
    GitSafetyError,
    assess_branch_delete,
    assess_checkout_target,
    assess_push,
    assess_reset,
    is_protected,
)
from oss_agent.safety.prompt_injection import (
    TRUST_BOUNDARY_NOTICE,
    InjectionFlag,
    has_injection,
    scan,
    summarize_flags,
    wrap_untrusted,
)
from oss_agent.safety.rate_limit import RateLimitExceeded, RateLimiter
from oss_agent.safety.secrets import (
    SecretMatch,
    contains_secret,
    redact,
    scan_text,
)

__all__ = [
    "CommandAssessment",
    "Danger",
    "assess_command",
    "is_dangerous",
    "DEFAULT_PROTECTED",
    "GitOpAssessment",
    "GitSafetyError",
    "assess_branch_delete",
    "assess_checkout_target",
    "assess_push",
    "assess_reset",
    "is_protected",
    "TRUST_BOUNDARY_NOTICE",
    "InjectionFlag",
    "has_injection",
    "scan",
    "summarize_flags",
    "wrap_untrusted",
    "RateLimitExceeded",
    "RateLimiter",
    "SecretMatch",
    "contains_secret",
    "redact",
    "scan_text",
]
