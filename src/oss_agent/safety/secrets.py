"""Secret detection.

Pure-stdlib heuristics that flag likely credentials in text (diffs, files,
command output, log records) *before* anything is committed, pushed, or logged.
This module is intentionally independent of the agent/LLM layer: safety checks
must not depend on agent reasoning.

Detection is heuristic and errs toward flagging. Callers decide whether a match
blocks (commit/push) or merely redacts (logs).
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SecretMatch:
    kind: str
    severity: str  # "high" | "medium" | "low"
    start: int
    end: int
    preview: str  # already-redacted preview, safe to log


# (name, severity, compiled pattern). Order matters only for reporting.
_PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    (
        "private_key_block",
        "high",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"),
    ),
    ("aws_access_key_id", "high", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    (
        "github_token",
        "high",
        re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b"),
    ),
    ("github_pat", "high", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b")),
    ("slack_token", "high", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("google_api_key", "high", re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b")),
    ("stripe_secret_key", "high", re.compile(r"\b[rs]k_live_[0-9A-Za-z]{16,}\b")),
    (
        "jwt",
        "medium",
        re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}\b"),
    ),
    (
        "bearer_token",
        "medium",
        re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-._~+/]{20,}=*\b"),
    ),
    (
        "generic_assignment",
        "medium",
        re.compile(
            r"(?i)\b(?:api[_-]?key|secret|token|passwd|password|pwd|client[_-]?secret|"
            r"access[_-]?token|auth[_-]?token|private[_-]?key)\b\s*[:=]\s*"
            r"['\"]?([A-Za-z0-9_\-./+=]{8,})['\"]?"
        ),
    ),
]

# Obvious placeholders that should never be treated as real secrets.
_PLACEHOLDERS = re.compile(
    r"(?i)^(?:x{3,}|\*{3,}|<[^>]+>|your[_-].*|example.*|changeme|placeholder|"
    r"dummy|test|fake|none|null|todo|redacted|\.{3,})$"
)


def _preview(text: str, start: int, end: int) -> str:
    """A short, already-redacted preview around the match."""
    frag = text[start:end]
    if len(frag) <= 8:
        masked = frag[0] + "***" if frag else "***"
    else:
        masked = f"{frag[:4]}…{frag[-2:]} (len={len(frag)})"
    return masked


def scan_text(text: str) -> list[SecretMatch]:
    """Return likely secret matches found in ``text``."""
    if not text:
        return []
    matches: list[SecretMatch] = []
    for kind, severity, pattern in _PATTERNS:
        for m in pattern.finditer(text):
            # For assignment patterns the credential is in group 1.
            value = m.group(1) if m.groups() else m.group(0)
            if value and _PLACEHOLDERS.match(value.strip()):
                continue
            start = m.start(1) if m.groups() else m.start(0)
            end = m.end(1) if m.groups() else m.end(0)
            matches.append(
                SecretMatch(
                    kind=kind,
                    severity=severity,
                    start=start,
                    end=end,
                    preview=_preview(text, start, end),
                )
            )
    return matches


def contains_secret(text: str) -> bool:
    return bool(scan_text(text))


def redact(text: str) -> str:
    """Return ``text`` with detected secret substrings masked.

    Safe to call on anything about to be logged. Never raises.
    """
    if not text:
        return text
    matches = scan_text(text)
    if not matches:
        return text
    # Replace from the end so earlier offsets stay valid.
    result = text
    for m in sorted(matches, key=lambda x: x.start, reverse=True):
        result = result[: m.start] + f"[REDACTED:{m.kind}]" + result[m.end :]
    return result
