# GitHub integration

The orchestration layer depends only on the `GitHubClient` interface
(`oss_agent.github.interface`). Concrete adapters are selected by
`create_github_client(settings)` from `OSS_AGENT_GITHUB_BACKEND`.

## Backends

| Backend | Class | Network | Auth | Use |
| --- | --- | --- | --- | --- |
| `mock` | `InMemoryGitHubClient` | none | none | tests, e2e, offline dev (default) |
| `gh` | `GhCliGitHubClient` | yes | `gh auth login` | production |
| `api` | — | — | token | documented future work (raises until implemented) |

## Interface surface

Read: `search_repositories`, `get_repository`, `search_issues`, `list_issues`,
`get_issue`, `get_file`, `list_files`, `list_pull_requests`, `get_pull_request`,
`find_pull_request_by_head`, `list_reviews`, `list_review_comments`,
`list_issue_comments`, `get_ci_status`.

Write: `create_pull_request` only. There is intentionally **no merge** method.

## The `gh` adapter (production)

`GhCliGitHubClient` shells out to `gh` through the controlled `CommandRunner` and a
`RateLimiter`, mapping `gh --json` / `gh api` output into domain models. It is a
real integration:

- If `gh` is missing (`exit 127`) or unauthenticated, calls raise `GitHubError`
  with a clear message — it never pretends to succeed.
- `create_pull_request` is idempotent: it reuses an existing PR for the same head
  branch instead of opening a duplicate.
- Merging is not implemented (spec: never auto-merge).

Setup: `gh auth login`, then `export OSS_AGENT_GITHUB_BACKEND=gh`.

## The mock adapter (tests / offline)

`InMemoryGitHubClient` is a fully functional, network-free adapter — not a fake
presented as live. It stores repositories, issues, and PRs in memory, honors
GitHub-style `label:` search qualifiers, and can serve repository file contents
from a local directory (`set_file_root`). This lets the end-to-end test drive
discovery and analysis against a genuine local fake repository. It guards against
path traversal when serving files.

## Adding the REST (`api`) backend

Implement `GitHubClient` against the REST API using `OSS_AGENT_GITHUB_TOKEN`, wire
it into `create_github_client`, and reuse the existing `RateLimiter` and
`CommandRunner`/HTTP client. No orchestration code changes are required.
