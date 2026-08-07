# Implementation status

Last updated: 2026-08-07

State vocabulary: `DONE`, `PARTIAL`, `IN_PROGRESS`, `BLOCKED`, `PENDING`.
`DONE (offline)` means the repository/software completion condition passed using fake
adapters; it does not imply target-host or real-model acceptance.

## Environment inventory

- Development path: `$HOME/wip/llm-platform`
- Host: macOS 26.4, arm64 development workstation; no production paths modified.
- Python: pyenv Python 3.13.13 (project target is Python 3.12+).
- `uv`: not detected; isolated stdlib venv/pip used and `requirements.lock` captured.
- NVIDIA/Slurm/cgroup: `nvidia-smi`, `scontrol`, `sinfo`, `squeue`, `sbatch`, and
  `sacct` unavailable; cgroup v2 not detected.
- Git: repository initialized on `main`; global author name/email not configured, so
  no local phase commits were created. No remote was added and nothing was pushed.

## Phase status

### Phase 0 — Repository foundation: DONE (offline), target foundation PENDING

Created the complete scaffold, authoritative requirements, contributor rules,
strict Pydantic schemas and example configuration, quality tooling, fake runtime and
Slurm foundations, read-only inventory, CI, production layout/service/Slurm/cgroup
templates, and dry-run installation scripts. `docs/requirements.md` exactly matches
the authoritative block (SHA-256
`14841bdf29a0872a75594c7bf345051850c7c6baaee246f300d6f5f411e37e83`).

Target-host GPU recognition, service accounts/directories, cgroup v2, MUNGE/Slurm,
and 1/2/3-GPU Slurm jobs remain PENDING. They require the Linux GPU server and
privileged reviewed application; this development run deliberately did not perform
them.

### Phase 1 — Runtime layer: DONE (mock contract), hardware PENDING

Implemented the common adapter contract, typed argument-array launch specifications,
llama.cpp and vLLM adapters, process/HTTP abstractions, fake adapter/backend,
health/metrics/proxy/SSE/cancel lifecycle, backend launcher, exact-version manifest,
and benchmark manifest/runner. Contract and command tests pass.

Real llama.cpp/vLLM builds, representative model starts, memory/throughput/tool
parser tests, sleep/wake capability validation, and GPU benchmarks are PENDING.

### Phase 2 — Gateway and manual routing: DONE (offline), live compatibility PENDING

Implemented health/readiness/metrics, Responses, Chat Completions, SSE, request IDs,
OpenAI-shaped errors, timeout/cancellation paths, unknown benign-field preservation,
dangerous extension rejection, hashed persistent keys/scopes/model permissions,
per-user concurrency, force/prefer routing, selected-route headers, route history and
admin explanation, SQL persistence primitives, Codex configuration, and fake Gateway
integration tests.

Real Codex CLI, real llama.cpp/vLLM, PostgreSQL restart, LAN/VPN/TLS, and live client
disconnect behavior remain PENDING.

### Phase 3 — Queue, Slurm and GPU orchestration: PARTIAL

Implemented a three-user fair queue, starvation guard, independent cancellation,
resource/profile planner, protected-job capacity check, backend state machine,
idempotent reconciler, active-stream drain, 2+1 ↔ 3-GPU fake transitions, fake and
CLI Slurm adapters, validated sbatch generation with job↔instance mapping, orphan
detection, dwell/switch-rate policy, circuit breaker, persistent request state, and
dry-run administrative commands.

Remaining software work: connect unavailable-gateway requests to the durable queue
and reconciler as one long-running control loop; persist desired profile/switch
history transactionally; implement opportunistic batch requeue policy; complete live
admin API mutations and failure/retry recovery. Real Slurm/GRES/cgroup/accounting and
restart tests are PENDING.

### Phase 4 — Per-user agent harness: PARTIAL

Implemented persistent task state, phase transitions, task features, manual route
overrides, repeated-failure escalation, Gateway client, safe listing/search/read and
conflict-checked replacement, allowlisted argument-array tools, path/symlink/absolute
executable protection, sensitive environment scrubbing, and a restart-persistent
vertical fixture test.

Remaining: reviewed automatic worktree creation under `/scratch`, a bounded inference
and tool-call loop, interactive route commands, human approval UI, patch/diff history,
and a real model-driven discover→finalize acceptance. The harness is explicitly
documented as a foundation, not a complete Codex replacement.

### Phase 5 — Automatic router: DONE (offline rules), benchmark acceptance PENDING

Implemented hard capability/context/permission/capacity/force filters, three policy
weight sets, measured deployment cost fields, loaded/batching/continuity/diversity
bonuses, manual prefer/force precedence, unbenchmarked exclusion, failure/high-risk
escalation reason codes, candidate explanations, and deterministic golden-style unit
fixtures. Actual model quality/speed baselines require registered benchmarks.

### Phase 6 — Evaluation and learned-router foundation: DONE (foundation)

Implemented the durable outcome table, offline success/elapsed/collapse evaluator,
stable A/B assignment, safety-constrained `LearnedRouter` protocol, and no-op baseline.
No learned model or statistical improvement is claimed: outcome data, a reviewed
golden task corpus, and sufficient samples do not yet exist.

## Verification evidence

Commands actually run in this workspace:

- `bash -n scripts/*.sh deploy/*.sh deploy/slurm/*.sh` — PASS.
- `./scripts/inventory-host.sh` — PASS (read-only; target tooling unavailable as above).
- `make check` — PASS on final code:
  - Ruff format/lint: PASS, 96 files formatted.
  - strict mypy: PASS, 57 source files.
  - unit: 30 passed.
  - integration: 10 passed.
  - security: 6 passed.
  - secret-pattern check: PASS.
  - aggregate non-hardware: 46 passed, 2 deselected; branch-aware coverage 72.56%
    against 70% minimum.
- `.venv/bin/python -m pytest -m hardware -q` — 2 SKIPPED by explicit opt-in guard;
  no real-hardware result claimed.
- Alembic `upgrade head` and `current` against a temporary async SQLite database —
  PASS at revision `0001 (head)`.
- `llmctl config validate --config-dir config` — PASS (2 models, 3 deployments).
- Installation layout, QOS, runtime build/env, benchmark, deployment, rollback, model
  registration, backup, and restore scripts — dry-run paths executed successfully;
  no host or service state changed.
- Authoritative requirement source/document SHA-256 comparison — exact match.

## Known limitations and blockers

The production Definition of Done is not satisfied. AT-001–AT-025 require target-host
execution; several also require remaining Phase 3/4 integration described above.
Example models/deployments are intentionally disabled and unbenchmarked. No runtime
or model revision, quantization, chat template, tool parser, VRAM/RAM fit, quality,
latency, or throughput has been accepted. Production config, service accounts,
secrets, TLS/VPN, PostgreSQL, Slurm, GPU, systemd, backup, and rollback have not been
applied or tested.

## Exact next step

On the target Linux GPU server, from this repository, run the single read-only command:

```bash
./scripts/inventory-host.sh
```

Record its output, resolve hardware/runtime placeholders, then execute the reviewed
Phase 0 service-account/directory/Slurm process outside this unprivileged development
run.
