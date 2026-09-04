"""Validated application configuration sourced from environment variables.

Nothing here is a secret literal. Secrets (like a GitHub token) are *read* from
the environment and never logged. See ``.env.example`` for the full list.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Annotated, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class GitHubBackend(str, Enum):
    MOCK = "mock"
    GH = "gh"
    API = "api"


class AgentBackend(str, Enum):
    MOCK = "mock"
    CLAUDE = "claude"


class LogFormat(str, Enum):
    TEXT = "text"
    JSON = "json"


class Settings(BaseSettings):
    """Runtime configuration. Instantiate via :func:`get_settings`."""

    model_config = SettingsConfigDict(
        env_prefix="OSS_AGENT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # GitHub
    github_backend: GitHubBackend = GitHubBackend.MOCK
    github_token: Optional[str] = None

    # Agent runtime
    agent_backend: AgentBackend = AgentBackend.MOCK
    claude_bin: str = "claude"

    # Storage & runtime
    database_url: str = "sqlite:///.oss-agent/oss_agent.db"
    worktree_root: Path = Path(".oss-agent/worktrees")
    state_dir: Path = Path(".oss-agent")

    # Behavior tuning
    max_review_iterations: int = Field(default=3, ge=1, le=20)
    max_debug_iterations: int = Field(default=3, ge=1, le=20)
    command_timeout_seconds: int = Field(default=600, ge=1)
    github_min_interval_seconds: float = Field(default=1.0, ge=0.0)
    log_level: str = "INFO"
    log_format: LogFormat = LogFormat.TEXT

    # NoDecode: accept a plain comma-separated env string; the validator splits it
    # (without it, pydantic-settings would try to JSON-decode the value first).
    protected_branches: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["main", "master", "develop", "release"]
    )
    allow_auto_merge: bool = False

    # Config file locations (not env-prefixed values but resolved paths).
    profile_path: Path = Path("config/user-profile.yaml")
    scoring_path: Path = Path("config/scoring.yaml")

    @field_validator("protected_branches", mode="before")
    @classmethod
    def _split_branches(cls, v: object) -> object:
        if isinstance(v, str):
            return [b.strip() for b in v.split(",") if b.strip()]
        return v

    @field_validator("log_level")
    @classmethod
    def _upper_level(cls, v: str) -> str:
        v = v.upper()
        if v not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"invalid log level: {v}")
        return v

    @property
    def github_token_present(self) -> bool:
        return bool(self.github_token and self.github_token.strip())

    def ensure_dirs(self) -> None:
        """Create runtime directories if missing (idempotent)."""
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.worktree_root.mkdir(parents=True, exist_ok=True)
        # If the sqlite DB lives under a directory, make sure it exists.
        if self.database_url.startswith("sqlite:///"):
            db_path = Path(self.database_url.replace("sqlite:///", "", 1))
            if db_path.parent and str(db_path.parent) not in (".", ""):
                db_path.parent.mkdir(parents=True, exist_ok=True)


_settings: Optional[Settings] = None


def get_settings(reload: bool = False, **overrides: object) -> Settings:
    """Return a process-wide :class:`Settings` singleton.

    ``overrides`` is primarily for tests, which construct isolated settings.
    """
    global _settings
    if overrides:
        return Settings(**overrides)  # type: ignore[arg-type]
    if _settings is None or reload:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Clear the cached singleton (used by tests)."""
    global _settings
    _settings = None
