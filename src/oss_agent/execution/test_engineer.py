"""Test engineer: runs the repository's real quality gates and captures results.

This is deterministic application logic, not agent reasoning: it determines which
commands to run from the repository report, executes them through the controlled
:class:`CommandRunner`, and records the exact command, exit code, output, and
duration. Test success is *measured*, never inferred.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from oss_agent.domain.models import (
    CommandOutcome,
    RepositoryReport,
    TestResult,
    TestSuiteResult,
)
from oss_agent.execution.runner import CommandResult, CommandRunner
from oss_agent.observability.logging import get_logger

logger = get_logger("execution.test_engineer")

_PYTEST_PASSED = re.compile(r"(\d+) passed")
_PYTEST_FAILED = re.compile(r"(\d+) failed")
_PYTEST_ERROR = re.compile(r"(\d+) error")


@dataclass(frozen=True)
class SuiteSpec:
    name: str
    kind: str
    command: str


class TestEngineer:
    def __init__(
        self,
        runner: Optional[CommandRunner] = None,
        *,
        python_executable: Optional[str] = None,
        timeout: int = 600,
    ) -> None:
        self._runner = runner or CommandRunner(default_timeout=timeout)
        self._python = python_executable or sys.executable
        self._timeout = timeout

    def _specs(self, report: RepositoryReport) -> list[SuiteSpec]:
        specs: list[SuiteSpec] = []
        if report.test_command:
            specs.append(SuiteSpec("tests", "unit", report.test_command))
        if report.lint_command:
            specs.append(SuiteSpec("lint", "lint", report.lint_command))
        if report.typecheck_command:
            specs.append(SuiteSpec("typecheck", "typecheck", report.typecheck_command))
        if report.build_command:
            specs.append(SuiteSpec("build", "build", report.build_command))
        return specs

    def _argv(self, command: str) -> list[str]:
        argv = shlex.split(command, posix=(sys.platform != "win32"))
        # Route "python"/"python3" to the chosen interpreter so the correct
        # environment (with the test tooling installed) is used.
        if argv and argv[0] in ("python", "python3", "py"):
            argv[0] = self._python
        return argv

    def _tool_available(self, argv: list[str]) -> bool:
        """Whether the command's executable can be found on this machine."""
        if not argv:
            return False
        exe = argv[0]
        if os.path.sep in exe or (os.path.altsep and os.path.altsep in exe):
            return os.path.exists(exe)
        return shutil.which(exe) is not None

    @staticmethod
    def _outcome(result: CommandResult) -> CommandOutcome:
        return CommandOutcome(
            command=result.command,
            cwd=result.cwd,
            exit_code=result.exit_code,
            duration_seconds=result.duration_seconds,
            stdout_tail=result.tail("stdout", 60),
            stderr_tail=result.tail("stderr", 60),
            timed_out=result.timed_out,
        )

    @staticmethod
    def _counts(text: str) -> tuple[Optional[int], Optional[int], Optional[int]]:
        passed = int(m.group(1)) if (m := _PYTEST_PASSED.search(text)) else None
        failed = int(m.group(1)) if (m := _PYTEST_FAILED.search(text)) else None
        errors = int(m.group(1)) if (m := _PYTEST_ERROR.search(text)) else None
        if failed is not None and errors:
            failed += errors
        total = None
        if passed is not None or failed is not None:
            total = (passed or 0) + (failed or 0)
        return total, passed, failed

    def run(
        self,
        report: RepositoryReport,
        worktree_path: str,
        *,
        only: Optional[list[str]] = None,
    ) -> TestResult:
        specs = self._specs(report)
        if only:
            specs = [s for s in specs if s.name in only]
        suites: list[TestSuiteResult] = []
        for spec in specs:
            argv = self._argv(spec.command)
            # A tool that isn't installed can't be run — record it as skipped
            # (excluded from the gate) instead of a false failure.
            if not self._tool_available(argv):
                empty = CommandResult(
                    command=argv, cwd=str(worktree_path), exit_code=127,
                    stdout="", stderr=f"tool not available: {argv[0]}",
                    duration_seconds=0.0, started_at=datetime.now(timezone.utc),
                )
                suites.append(TestSuiteResult(
                    name=spec.name, kind=spec.kind, passed=False, skipped=True,
                    command=self._outcome(empty),
                ))
                logger.info("suite skipped (tool unavailable)", extra={"suite": spec.name})
                continue
            result = self._runner.run(argv, cwd=worktree_path, timeout=self._timeout)
            combined = f"{result.stdout}\n{result.stderr}"
            total, passed, failed = self._counts(combined)
            suite = TestSuiteResult(
                name=spec.name,
                kind=spec.kind,
                passed=result.ok,
                skipped=(result.exit_code == 127),
                tests_total=total,
                tests_passed=passed,
                tests_failed=failed,
                command=self._outcome(result),
            )
            logger.info(
                "suite executed",
                extra={"suite": spec.name, "passed": suite.passed, "exit_code": result.exit_code},
            )
            suites.append(suite)

        executed = [s for s in suites if not s.skipped]
        skipped = [s for s in suites if s.skipped]
        passed_n = sum(1 for s in executed if s.passed)
        summary = f"{passed_n}/{len(executed)} executed suite(s) passed"
        if skipped:
            summary += f"; {len(skipped)} skipped ({', '.join(s.name for s in skipped)})"
        return TestResult(
            repository_full_name=report.repository.full_name,
            suites=suites,
            summary=summary + ".",
            confidence=1.0,  # measured, not inferred
        )
