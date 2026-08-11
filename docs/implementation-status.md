# Implementation status

Last updated: 2026-08-11

State vocabulary: `DONE`, `PARTIAL`, `IN_PROGRESS`, `BLOCKED`, `PENDING`.
`DONE (offline)` means the repository/software completion condition passed using fake
adapters; it does not imply target-host or real-model acceptance.

## Target hardware evidence supplied by the operator

The operator reports Ubuntu 26.04, Slurm 25.11.2/MUNGE, cgroup v2 device
confinement, three RTX 5060 Ti 16 GB GPUs, successful 1/2/3-GPU allocations,
service identities and production directories, llama.cpp b10356 at commit
`0666ad2b2b2452668733729e8b54234f5964643a`, vLLM 0.27.0 with torch
2.13.0+cu132, and successful OpenAI-compatible llama.cpp/vLLM smoke requests through
Slurm as `svc-llm`. This is operator-supplied evidence; this change did not rerun or
independently inspect the privileged host configuration.

The operator additionally reports successful production Gateway-to-llama.cpp
acceptance, backend READY and cleanup, correct service/job identities, and a normal
Gateway restart in approximately 0.2 seconds. A prior unavailable-backend request
exposed an unbounded shutdown wait. The Gateway now signals the control plane as
soon as Uvicorn receives an exit signal, cancels backend/profile/queue waiters,
and retains a bounded five-second grace period for active inference before Uvicorn
cancellation. The operator's production rerun measured 0.276 seconds and confirmed
HTTP/request-task cancellation, but PostgreSQL inspection found the cancelled row
still `queued`; two rows from earlier crashes were also stale. The follow-up fix
isolates terminalization in a bounded cleanup task that the lifespan finalizer drains,
and startup atomically fails any residual `queued`, `assigned`, or `running` rows with
`gateway_restarted`. Production verification of that follow-up is pending.

Verification for the shutdown fix:

- Focused persistence, control-plane, and Gateway tests: PASS, 18 tests, including
  an actual Uvicorn TCP server shutdown lifecycle and delayed DB terminalization.
- Ruff format and lint: PASS.
- strict mypy: PASS, 59 source files.
- `git diff --check`: PASS.
- `make check`: PASS: 61 unit, 22 integration, 6 security, and 89 aggregate
  non-hardware tests; secret-pattern check PASS; coverage 77.24% against 70%.

## Development environment inventory

- Development path: `$HOME/wip/llm-platform`
- Host for this implementation run: Linux workspace; no production paths modified.
- Python: 3.14.4 virtual environment (project target is Python 3.12+).
- `uv`: not detected; isolated stdlib venv/pip used and `requirements.lock` captured.
- Work is on `feature/phase3-real-hardware-integration`; nothing was pushed.

## Phase status

### Phase 0 — Repository foundation: DONE; target foundation OPERATOR-VERIFIED

Created the complete scaffold, authoritative requirements, contributor rules,
strict Pydantic schemas and example configuration, quality tooling, fake runtime and
Slurm foundations, read-only inventory, CI, production layout/service/Slurm/cgroup
templates, and dry-run installation scripts. `docs/requirements.md` exactly matches
the authoritative block (SHA-256
`14841bdf29a0872a75594c7bf345051850c7c6baaee246f300d6f5f411e37e83`).

Target-host GPU recognition, service accounts/directories, cgroup v2, MUNGE/Slurm,
and 1/2/3-GPU Slurm jobs are reported verified by the operator. No privileged changes
were made during this implementation.

### Phase 1 — Runtime layer: DONE (mock contract); runtime smoke OPERATOR-VERIFIED

Implemented the common adapter contract, typed argument-array launch specifications,
llama.cpp and vLLM adapters, process/HTTP abstractions, fake adapter/backend,
health/metrics/proxy/SSE/cancel lifecycle, backend launcher, exact-version manifest,
and benchmark manifest/runner. Contract and command tests pass.

Real llama.cpp/vLLM installs and Qwen3-0.6B API smoke starts are operator-verified.
Representative production benchmarks, memory/throughput/tool parser acceptance, and
sleep/wake capability decisions remain PENDING.

### Phase 2 — Gateway and manual routing: DONE (offline), live compatibility PENDING

Implemented health/readiness/metrics, Responses, Chat Completions, SSE, request IDs,
OpenAI-shaped errors, timeout/cancellation paths, unknown benign-field preservation,
dangerous extension rejection, hashed persistent keys/scopes/model permissions,
per-user concurrency, force/prefer routing, selected-route headers, route history and
admin explanation, SQL persistence primitives, Codex configuration, and fake Gateway
integration tests.

Real Codex CLI, real llama.cpp/vLLM, PostgreSQL restart, LAN/VPN/TLS, and live client
disconnect behavior remain PENDING.

### Phase 3 — Queue, Slurm and GPU orchestration: IN_PROGRESS

The Gateway now creates a long-running queue/planner/reconciler loop. Production
constructs llama.cpp/vLLM adapters dynamically, uses `CliSlurmAdapter`, renders an
optional-QOS sbatch script without deprecated user impersonation, and launches through
the restricted local helper as `svc-llm`. It attaches proxy/health
clients without a second local process, publishes only READY instances, drains active
requests before cancellation, and applies retry-budget circuit breaking. Startup
reconciliation reconstructs enabled known instances from existing `svc-llm` jobs and
preserves an exact matching profile. Unknown/disabled jobs are reported as orphans.
Stop reconciliation now waits asynchronously for Slurm to report the allocation gone
or terminal before reporting a deployment stopped; a bounded timeout produces a
structured stop failure and retains the instance for later reconciliation.

Balanced, strong-shared, and idle profiles remain configurable pending benchmarked
production model registration. Disabled Qwen3-0.6B llama.cpp/vLLM smoke deployments
and guarded end-to-end hardware tests were added. Remaining work includes executing
those integration tests on the target, durable switch history, opportunistic batch
requeue, and live admin mutations. The desired profile is persisted.

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

Commands actually run in this workspace for the 2026-08-11 change are below.
Hardware tests are guarded and were not run in this unprivileged workspace; no new
real-GPU claim is made from this test run.

- API-key provisioning FK-order fix — PASS: 2 focused integration tests use a
  file-backed SQLite database with foreign-key enforcement enabled. They cover an
  empty users table, a second key for an existing user, authentication of both
  returned plaintext keys against their persisted hashes, and rollback after a
  forced key uniqueness failure following the user flush (no partial user or key).
  Repository-wide Ruff format/check, strict mypy (80 checked files), and
  `git diff --check` PASS. `make check` repeated the Ruff and source-mypy passes,
  then reproduced the documented `aiosqlite`/Python 3.14 stall after the first three
  authentication tests and was interrupted after no further output; no full-suite
  or aggregate-coverage PASS is claimed.
- Production console entry-point fix — PASS: 5 focused tests resolve all three
  declarations from `pyproject.toml`, verify `--help` exits successfully without
  loading Gateway configuration, starting Uvicorn, or listening on a submit socket,
  and verify parsing of the Gateway `--config` option and all four submit-helper
  path options. Repository-wide Ruff format/check, strict mypy (79 checked files),
  and `git diff --check` PASS. An offline editable reinstall with
  `pip install --no-build-isolation --no-deps -e .` PASS, followed by successful
  installed-script help invocations for `llm-platform`, `llm-backend-submit`, and
  `llm-backend`. `make check` started successfully and repeated those Ruff and
  source-mypy passes, then reproduced the documented async SQLite stall after the
  first three authentication tests; it was interrupted after no further output, so
  no full-suite or aggregate-coverage PASS is claimed.
- Slurm shutdown synchronization fix — PASS: 7 focused orchestration integration
  tests (`pytest tests/integration/test_orchestration.py -q -p no:cov`) cover
  active-request draining, delayed `RUNNING` cancellation, timeout failure, and
  already-gone idempotency. A combined orchestration/control-plane run completed its
  test bodies but reproduced the known async teardown hang and was interrupted. The
  guarded hardware test was not run in this workspace. Ruff format/lint, strict mypy,
  and `git diff --check` PASS.

- Slurm sbatch directive-order fix — PASS: 27 focused CLI/helper tests verify the
  shebang remains first, every required and optional `#SBATCH` directive precedes
  `set -euo pipefail`, and both current-user and helper submission modes retain QOS
  behavior. Ruff format/lint and strict mypy PASS (105 files; 59 source files).
- Backend entry-point/startup-failure fix — focused Ruff format/lint PASS; 1 console
  entry-point unit test and 4 orchestration integration tests PASS. The integration
  coverage includes a submitted Slurm job that immediately enters `FAILED`, increments
  the circuit breaker, and returns a structured reconciliation `start` failure.
- Editable reinstall — PASS with `pip install --no-build-isolation --no-deps -e .`.
  `.venv/bin/llm-backend --help`, installed `--print-spec`, and the equivalent
  `python -m llm_platform.runtimes.backend_main --print-spec` invocation all PASS.
  The initial build-isolated reinstall attempted an unavailable offline build dependency;
  no network package was installed.
- `make check` — STARTED: Ruff and strict mypy passed; the unit suite again stalled in
  async SQLite tests after the first three authentication tests and was interrupted.
  A follow-up unit run excluding the previously identified authentication test advanced
  through the new console-entry-point test and config tests, then also stalled in the
  async persistence tests. No full-suite or aggregate-coverage PASS is claimed.
- Slurm helper/CLI coverage suite — PASS: 26 tests covering the fixed helper protocol,
  reviewed-deployment resolution, injection rejection, Unix stream handling, optional
  QOS, current-user and production-helper submission, and Slurm failure propagation;
  focused branch coverage was 74.52% across the two production modules.
- Ruff format/lint for the changed tests — PASS.
- `make check` — STARTED: Ruff and strict mypy passed; the unit suite then stalled in
  the pre-existing async SQLite authentication test after its first three tests. The
  command was interrupted; no full-suite or aggregate-coverage PASS is claimed from
  this sandbox run.
- Slurm submit integration targeted suite — PASS: 15 tests covering optional/configured
  QOS, current-user gating, helper transport/request rejection, and reconciliation error
  reporting.
- Ruff format/lint and strict mypy — PASS (104 files; 59 source files).
- `make check` — STARTED; lint and typecheck passed, but the pre-existing async SQLite
  authentication test did not complete in this sandbox. A direct 30-second run of
  `test_sqlalchemy_key_store_authenticates_persisted_hash` reproduced the stall. The
  command was interrupted; no full-suite PASS is claimed for this change.

- `make check` — PASS: Ruff and strict mypy passed; 30 unit, 12 integration,
  and 6 security tests passed; aggregate 48 non-hardware tests passed with 70.63%
  branch-aware coverage.
- `.venv/bin/python -m pytest -m hardware -q` — 4 SKIPPED by the explicit opt-in
  guard, including both real-runtime orchestrator/Gateway cases.
- Alembic upgrade/current against a dedicated temporary SQLite database — PASS at
  revision `0002 (head)`.
- `llmctl config validate --config-dir config` — PASS (3 models, 5 deployments).
- shell syntax checks and `deploy/install-layout.sh --dry-run` — PASS; no production
  path was modified.

Earlier baseline evidence:

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
