# Agent harness capabilities and limits

The initial `agent` CLI is a safe stateful harness foundation, not a complete Codex
replacement. It persists task phase, plan, tests, unresolved items, overrides, route
reasons, request IDs, and approvals under the user's private data directory. A model
server restart does not erase this state.

Implemented local tools are file listing/search/read, conflict-checked replacement,
allowlisted argument-array commands, and git/lint/type/test/build commands. Paths are
contained in the workspace and symlink targets are rejected. In-place editing is off
unless explicitly enabled. A production integration should create a task worktree at
`/scratch/$USER/agent-worktrees/<task-id>` and pass that directory as the workspace.

The state sequence is DISCOVER → PLAN → IMPLEMENT → TEST, with DEBUG on failure,
REVIEW after successful checks, and FINALIZE after review. Repeating an identical
failure twice changes an unlocked route policy to `auto/quality`. High-risk task
features request an independent final review, preferring another model family when a
safe eligible family exists.

The current CLI does not autonomously synthesize patches or execute an unbounded
agent loop. It provides the safety, persistence, feature, override, and Gateway client
components for a reviewed loop. `sudo`, push, deployment, destructive git operations,
unknown commands, network transfer tools, absolute paths, traversal, and workspace
symlinks are rejected rather than delegated to model output.
