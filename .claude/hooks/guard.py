#!/usr/bin/env python3
"""OSS-Agent PreToolUse safety hook.

Deterministic, self-contained (no imports beyond the stdlib) so it is simple and
auditable. It reads the Claude Code PreToolUse payload from stdin and blocks:

* dangerous shell commands (destructive filesystem ops, fork bombs, pipe-to-shell)
* git pushes to protected branches and force-pushes
* writing likely secrets into files

Blocking is done by exiting with code 2 and printing a reason to stderr, per the
Claude Code hook protocol. On any internal error it allows the call (it cannot
assert danger it did not detect) but never silently blocks legitimate work.
"""

from __future__ import annotations

import json
import re
import sys

PROTECTED = ("main", "master", "develop", "release")

DANGEROUS = [
    r"\brm\s+(-[a-z]*\s+)*-[a-z]*[rf][a-z]*\s+(-[a-z]+\s+)*(/|~|/\*|\$HOME)(\s|$)",
    r"\bdd\b.*\bof=/dev/",
    r"\bmkfs(\.\w+)?\b",
    r":\(\)\s*\{\s*:\|:&\s*\}\s*;\s*:",
    r"\b(shutdown|reboot|halt|poweroff)\b",
    r"\b(curl|wget)\b[^|]*\|\s*(sudo\s+)?(sh|bash|zsh)\b",
    r"\bchmod\s+-R\s+0*777\s+/",
]

GIT_FORCE = re.compile(r"\bgit\s+push\b.*(--force(?!-with-lease)|\s-f\b)")
GIT_PUSH = re.compile(r"\bgit\s+push\b")

SECRETS = [
    r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----",
    r"\bAKIA[0-9A-Z]{16}\b",
    r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b",
    r"\bgithub_pat_[A-Za-z0-9_]{22,}\b",
    r"\b[rs]k_live_[0-9A-Za-z]{16,}\b",
    r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b",
]
_PLACEHOLDER = re.compile(r"(?i)(your[_-]|example|changeme|placeholder|dummy|<[^>]+>)")


def block(reason: str) -> None:
    print(f"[oss-agent guard] BLOCKED: {reason}", file=sys.stderr)
    sys.exit(2)


def check_bash(command: str) -> None:
    for pat in DANGEROUS:
        if re.search(pat, command):
            block(f"dangerous command pattern: {pat}")
    if GIT_FORCE.search(command):
        block("force-push is not permitted")
    if GIT_PUSH.search(command):
        for br in PROTECTED:
            if re.search(rf"\bpush\b.*\b(origin\s+)?{re.escape(br)}\b", command):
                block(f"refusing to push to protected branch '{br}'")


def check_write(text: str) -> None:
    for pat in SECRETS:
        m = re.search(pat, text)
        if m and not _PLACEHOLDER.search(m.group(0)):
            block(f"likely secret in file content: {pat}")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # cannot parse -> cannot assert danger
    tool = payload.get("tool_name", "")
    args = payload.get("tool_input", {}) or {}
    try:
        if tool == "Bash":
            check_bash(str(args.get("command", "")))
        elif tool in ("Write", "Edit", "MultiEdit"):
            content = args.get("content") or args.get("new_string") or ""
            if tool == "MultiEdit":
                content = " ".join(e.get("new_string", "") for e in args.get("edits", []))
            check_write(str(content))
    except SystemExit:
        raise
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
