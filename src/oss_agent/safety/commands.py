"""Dangerous command detection.

Deterministic, allow/deny assessment of shell commands before they run. This is a
defense-in-depth layer: the execution engine consults it, and the ``pretooluse``
hook consults an equivalent policy. It errs toward blocking destructive or
network-piped-to-shell operations.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence


class Danger(str, Enum):
    SAFE = "safe"
    SUSPICIOUS = "suspicious"
    DANGEROUS = "dangerous"


@dataclass(frozen=True)
class CommandAssessment:
    danger: Danger
    reasons: list[str] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return self.danger is Danger.DANGEROUS

    @property
    def allowed(self) -> bool:
        return not self.blocked


# Patterns evaluated against the normalized command string.
_DANGEROUS: list[tuple[str, re.Pattern[str]]] = [
    ("recursive force delete of root/home", re.compile(r"\brm\s+(-[a-z]*\s+)*-[a-z]*[rf][a-z]*\s+(-[a-z]+\s+)*(/|~|/\*|\$HOME|\.\.?/?)(\s|$)")),
    ("recursive delete of filesystem root", re.compile(r"\brm\s+.*\s(/|/\*)(\s|$)")),
    ("disk overwrite via dd", re.compile(r"\bdd\b.*\bof=/dev/")),
    ("filesystem format", re.compile(r"\bmkfs(\.\w+)?\b|\bformat\s+[A-Za-z]:")),
    ("fork bomb", re.compile(r":\(\)\s*\{\s*:\|:&\s*\}\s*;\s*:")),
    ("system shutdown/reboot", re.compile(r"\b(shutdown|reboot|halt|poweroff)\b")),
    ("world-writable recursive chmod at root", re.compile(r"\bchmod\s+-R\s+0*777\s+/")),
    ("pipe remote script to shell", re.compile(r"\b(curl|wget)\b[^|]*\|\s*(sudo\s+)?(sh|bash|zsh|python\d?|perl|ruby)\b")),
    ("write to system directory", re.compile(r">\s*/(etc|bin|sbin|usr|boot|sys|proc)/")),
    ("git history destruction", re.compile(r"\bgit\s+push\b.*--force(?!-with-lease)|\bgit\s+push\b.*\s-f\b")),
    ("recursive force powershell delete at drive root", re.compile(r"(?i)Remove-Item\b.*-Recurse\b.*-Force\b.*[A-Za-z]:\\?(\s|$|'|\")")),
    ("windows recursive delete", re.compile(r"(?i)\b(rd|rmdir)\s+/s\s+/q\s+[A-Za-z]:\\?")),
]

_SUSPICIOUS: list[tuple[str, re.Pattern[str]]] = [
    ("privilege escalation", re.compile(r"\bsudo\b|\bsu\s+-\b")),
    ("network download to file", re.compile(r"\b(curl|wget)\b")),
    ("history rewrite", re.compile(r"\bgit\s+(reset\s+--hard|clean\s+-[a-z]*d|filter-branch|rebase)\b")),
    ("environment dump", re.compile(r"\b(printenv|env)\b|\becho\s+\$[A-Z_]+")),
    ("eval of dynamic input", re.compile(r"\beval\b|\bexec\b")),
    ("changes file permissions broadly", re.compile(r"\bchmod\s+-R\b|\bchown\s+-R\b")),
]


def _normalize(command: str | Sequence[str]) -> str:
    if isinstance(command, str):
        return command.strip()
    return " ".join(shlex.quote(part) if " " in part else part for part in command).strip()


def assess_command(command: str | Sequence[str]) -> CommandAssessment:
    """Classify a command as SAFE, SUSPICIOUS, or DANGEROUS."""
    text = _normalize(command)
    if not text:
        return CommandAssessment(Danger.SAFE)

    dangerous_reasons = [name for name, pat in _DANGEROUS if pat.search(text)]
    if dangerous_reasons:
        return CommandAssessment(Danger.DANGEROUS, dangerous_reasons)

    suspicious_reasons = [name for name, pat in _SUSPICIOUS if pat.search(text)]
    if suspicious_reasons:
        return CommandAssessment(Danger.SUSPICIOUS, suspicious_reasons)

    return CommandAssessment(Danger.SAFE)


def is_dangerous(command: str | Sequence[str]) -> bool:
    return assess_command(command).blocked
