# Security & threat model

Security controls are **deterministic** and **independent of agent reasoning**.
They live in `oss_agent.safety` and in the fail-closed Claude hook
[`.claude/hooks/guard.py`](../.claude/hooks/guard.py). An LLM cannot talk its way
past them.

## Trust boundary

There are two classes of input:

1. **System instructions** — this project's constitution, safety rules, and the
   orchestrator's control flow. Highest priority.
2. **Untrusted repository content** — READMEs, issues, comments, source, tests, CI
   configs, maintainer messages.

Untrusted content can inform *what the code should do*. It can **never**:
change how OSS-Agent behaves, relax or disable a safety rule, exfiltrate secrets,
redirect network/filesystem access, or alter tool permissions.

Before untrusted text reaches an agent it is wrapped and labeled
(`safety.prompt_injection.wrap_untrusted`). Suspicious content is flagged
(`safety.prompt_injection.scan`) and recorded on the workflow — never obeyed.

## Threats considered

| Threat | Mitigation |
| --- | --- |
| Prompt injection in README/issue/source/comments | trust boundary + `scan` flags + security-reviewer check; content is data, not instructions |
| Malicious repository / test / shell script | dangerous-command detection; scripts not run blindly; execution is captured and bounded |
| Secret exfiltration | secret scan before commit/push; log redaction; `.env` git-ignored; deny-read of `.env`/keys in `settings.json` |
| GitHub token abuse | `gh` backend uses gh's own auth; rate limiting; PR-only writes; no merge |
| Destructive git operations | protected-branch push blocked; force-push blocked; hard-reset/branch-delete of protected branches blocked |
| Dependency attacks | security-reviewer flags risky dependency additions |
| Duplicate / spam contributions | duplicate detection; one PR per issue; idempotent PR creation |
| Untrusted maintainer comments | treated as data; injection flagged; replies drafted for human approval |

## Deterministic controls

- **`safety.secrets`** — detects private keys, cloud keys, GitHub/Slack/Stripe
  tokens, JWTs, and generic credential assignments; powers commit/push blocking
  and log redaction. Placeholders are ignored.
- **`safety.commands`** — classifies commands SAFE / SUSPICIOUS / DANGEROUS and
  blocks destructive or pipe-to-shell operations.
- **`safety.git_safety`** — protected-branch, force-push, reset, and delete rules.
- **`safety.prompt_injection`** — trust-boundary wrapping and injection scanning.
- **`safety.rate_limit`** — bounded, minimum-interval API access.

## Defense in depth

1. Prompts wrap untrusted content and state the trust boundary.
2. The security-reviewer agent explicitly checks for injection and unsafe code.
3. `oss_agent.safety` enforces the rules regardless of what any agent decides.
4. `.claude/hooks/guard.py` fails closed on dangerous commands, protected-branch
   pushes, force-pushes, and secret writes — even for interactive Claude Code use.
5. `.claude/settings.json` denies reads of `.env`/keys and asks before any push or
   PR merge.

## PR safety

Pull requests are gated behind passing tests plus code, security, and maintainer
approval, and in-scope changes. **Merging is never automatic** and is disabled by
default (`OSS_AGENT_ALLOW_AUTO_MERGE=false`).

## Reporting

This is a defensive, authorized-use system. Do not use it to target repositories
without permission or to bypass any project's contribution norms.
