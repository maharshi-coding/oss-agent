"""Controlled command execution layer.

Every command runs through :class:`CommandRunner`, which captures the command,
working directory, exit code, stdout, stderr, duration, and timestamp. It enforces
timeouts and output limits, and consults the dangerous-command policy before
executing. Output is never silently discarded.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional, Sequence

from oss_agent.observability.logging import get_logger
from oss_agent.safety.commands import Danger, assess_command

logger = get_logger("execution")

_DEFAULT_OUTPUT_LIMIT = 200_000  # characters retained per stream


class DangerousCommandError(RuntimeError):
    """Raised when execution of a command classified DANGEROUS is attempted."""


@dataclass(frozen=True)
class CommandResult:
    command: list[str]
    cwd: str
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    started_at: datetime
    timed_out: bool = False
    truncated: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    def tail(self, stream: str, lines: int = 40) -> str:
        text = self.stdout if stream == "stdout" else self.stderr
        return "\n".join(text.splitlines()[-lines:])


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    head = text[: limit // 2]
    tail = text[-limit // 2 :]
    return f"{head}\n…[truncated {len(text) - limit} chars]…\n{tail}", True


class CommandRunner:
    """Runs subprocesses with capture, timeout, and safety gating."""

    def __init__(
        self,
        *,
        default_timeout: int = 600,
        output_limit: int = _DEFAULT_OUTPUT_LIMIT,
        allow_suspicious: bool = True,
        env: Optional[Mapping[str, str]] = None,
    ) -> None:
        self.default_timeout = default_timeout
        self.output_limit = output_limit
        self.allow_suspicious = allow_suspicious
        self._env = dict(env) if env is not None else None

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Optional[str | Path] = None,
        timeout: Optional[int] = None,
        env: Optional[Mapping[str, str]] = None,
        input_text: Optional[str] = None,
        check: bool = False,
        enforce_safety: bool = True,
    ) -> CommandResult:
        """Execute ``command`` (an argv list) and capture the result.

        Raises :class:`DangerousCommandError` if the command is classified as
        DANGEROUS and ``enforce_safety`` is set. Never raises on non-zero exit
        unless ``check`` is true.
        """
        argv = [str(c) for c in command]
        workdir = str(cwd) if cwd is not None else str(Path.cwd())
        timeout = timeout if timeout is not None else self.default_timeout

        if enforce_safety:
            assessment = assess_command(argv)
            if assessment.danger is Danger.DANGEROUS:
                logger.error(
                    "blocked dangerous command",
                    extra={"reasons": ";".join(assessment.reasons), "cwd": workdir},
                )
                raise DangerousCommandError(
                    f"blocked dangerous command {argv!r}: {', '.join(assessment.reasons)}"
                )
            if assessment.danger is Danger.SUSPICIOUS and not self.allow_suspicious:
                raise DangerousCommandError(
                    f"blocked suspicious command {argv!r}: {', '.join(assessment.reasons)}"
                )

        run_env = None
        if self._env is not None or env is not None:
            import os

            run_env = dict(os.environ)
            if self._env:
                run_env.update(self._env)
            if env:
                run_env.update(env)

        started_at = datetime.now(timezone.utc)
        start = time.monotonic()
        timed_out = False
        try:
            proc = subprocess.run(
                argv,
                cwd=workdir,
                env=run_env,
                input=input_text,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
            stdout, stderr, exit_code = proc.stdout, proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            exit_code = 124
        except FileNotFoundError as exc:
            duration = time.monotonic() - start
            logger.error("command not found", extra={"command": argv[0]})
            return CommandResult(
                command=argv, cwd=workdir, exit_code=127,
                stdout="", stderr=str(exc), duration_seconds=round(duration, 4),
                started_at=started_at, timed_out=False,
            )

        duration = time.monotonic() - start
        stdout_t, t1 = _truncate(stdout or "", self.output_limit)
        stderr_t, t2 = _truncate(stderr or "", self.output_limit)
        result = CommandResult(
            command=argv,
            cwd=workdir,
            exit_code=exit_code,
            stdout=stdout_t,
            stderr=stderr_t,
            duration_seconds=round(duration, 4),
            started_at=started_at,
            timed_out=timed_out,
            truncated=t1 or t2,
        )
        logger.debug(
            "command executed",
            extra={
                "command": " ".join(argv),
                "cwd": workdir,
                "exit_code": exit_code,
                "duration": result.duration_seconds,
                "timed_out": timed_out,
            },
        )
        if check and not result.ok:
            raise subprocess.CalledProcessError(exit_code, argv, stdout_t, stderr_t)
        return result
