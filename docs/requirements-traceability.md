# Requirements traceability

The authoritative requirement text is `docs/requirements.md`. `PASS (fake)` means an
offline test passed using mock/fake components; it is not real-host acceptance.

## Requirement groups

| Requirement | Implementation evidence | Test/evidence | State |
|---|---|---|---|
| Architecture and separation, §6 | package boundaries, `docs/architecture.md`, ADR-0001 | documentation + security review | DONE (offline) |
| Harness and safety, §8 | `agent_harness/*` | vertical and security suites | PARTIAL |
| Gateway API/errors/auth, §9 | `gateway/*`, `auth/*`; early server-exit notification and bounded active-request grace | `test_gateway.py`, `test_auth.py`, shutdown integration regression | PASS (fake) |
| Router, §10 | `routing/router.py`; four canonical policy weight sets and legacy quality alias | `test_routing.py` selector, tier-selection, force, escalation, and hard-filter coverage | PASS (fake) |
| Model/deployment registry, §11 | strict config + SQL models | config tests, validation CLI | DONE (offline) |
| Dynamic model skills and user AgentProfiles | `agent_profiles` + append-only `model_skill_evaluations`, authenticated profile/evaluation/capability APIs, admin CLI | repository aggregation/idempotency, dynamic Gateway, ownership/model-permission, CLI, and SQLite migration tests | PASS pending full-suite rerun |
| Planner/state transitions, §12 | scheduler + long-running control plane + reconciler | scheduler/orchestration/recovery tests, including structured immediate Slurm startup failure and bounded allocation-release polling on stop | PASS (fake); hardware test guarded |
| Fair queue/cancel, §13 | `queueing/fair.py` + persistent request repository; shutdown-cancellable backend waits; startup terminalization of stale work | three-user/cancel/starvation tests; actual Uvicorn shutdown with delayed terminal DB cleanup; queued/assigned/running startup recovery | PASS (SQLite); follow-up PostgreSQL rerun pending |
| Runtime adapters, §14 | llama.cpp/vLLM/fake adapters | adapter contracts | PASS (mock); hardware pending |
| Slurm, §15 | CLI/fake adapters, optional-QOS sbatch rendering, validated svc-llm Unix-socket helper | QOS modes, fixed-schema rejection, helper/current-user modes, submission and terminal-start reconciliation errors, guarded real-runtime tests | host foundation user-verified; orchestration rerun and installed-helper identity acceptance pending |
| Store/cache/layout, §16–17 | config, deploy templates, scripts | dry-run review | PARTIAL; host pending |
| Persistence/privacy, §18 | SQLAlchemy request + desired-profile repositories/Alembic; atomic unfinished-request recovery | DB/idempotency/migration and shutdown/restart recovery tests | PASS (SQLite); PostgreSQL exposed pre-fix stale rows, follow-up rerun pending |
| Metrics/logs/alerts, §19 | Prometheus + redacted structured logging | metrics/privacy tests | PARTIAL; host alerts pending |
| NFR-001–020 | systemd, state/recovery, adapters, config, runbooks | offline suites and dry-runs | PARTIAL |
| Admin/user CLI, §21–22 | `admin_cli/*`, `agent_harness/cli.py` | config CLI + dry-run commands | PARTIAL |
| Backup/recovery, §23 | scripts and runbooks | dry-run paths | PARTIAL; restore drill pending |
| Tests, §24 | unit/integration/security/hardware markers | `make check` | PASS offline |
| Evaluation/learned router, Phase 6 | outcomes/evaluation/LearnedRouter | evaluator tests | DONE foundation only |

## Acceptance tests

| ID | Offline evidence | Current state |
|---|---|---|
| AT-001 | balanced 2+1 fake profile starts | PASS (fake); 1/2/3-GPU allocation user-verified |
| AT-002 | two-large selection and 3-GPU shared fake profile | PASS (fake); real sharing pending |
| AT-003 | exact three-user round robin | PASS |
| AT-004 | forced llama.cpp never falls back | PASS (fake) |
| AT-005 | forced vLLM route header + guarded Slurm smoke | PASS (fake); hardware integration test added |
| AT-006 | explicit runtime failure states/retry primitives; immediate terminal Slurm jobs surface structured start failures | PARTIAL; real crash recovery rerun pending |
| AT-007 | circuit breaker stops restart loop | PASS policy; real OOM pending |
| AT-008 | active request drains before profile stop; stopped is withheld until Slurm releases the allocation | PASS (fake); real shutdown rerun pending |
| AT-009 | balanced drains then 3-GPU shared starts | PASS (fake) |
| AT-010 | protected GPU capacity blocks switch | PASS (fake) |
| AT-011 | QOS template documents opportunistic requeue | PENDING implementation/host |
| AT-012 | path/symlink/workspace writes protected | PASS harness; OS cross-user pending |
| AT-013 | request logs omit prompt body | PASS |
| AT-014 | token patterns/redaction and cache separation documented | PARTIAL; host permissions pending |
| AT-015 | model rollback dry-run/runbook | PARTIAL; real drill pending |
| AT-016 | runtime version rollback dry-run/runbook | PARTIAL; real drill pending |
| AT-017 | persistent unfinished requests + startup Slurm attach/health registry | PASS offline; reboot drill pending |
| AT-018 | repeated identical failures select canonical strong policy | PASS |
| AT-019 | high-risk/diverse-family router reasons | PARTIAL; enforced final loop pending |
| AT-020 | unsupported forced runtime returns explicit error | PASS |
| AT-021 | one shared-queue cancellation leaves neighbor assigned | PASS |
| AT-022 | strict unknown/path/bind/schema validation | PASS |
| AT-023 | disk-full runbook exists | PENDING automated acquisition gate/alert |
| AT-024 | admin route explanation returns model/runtime/reasons | PASS (fake) |
| AT-025 | Chat Completions through one base URL | PASS (fake); real client pending |

See `docs/implementation-status.md` for exact commands, totals, blockers, and next step.
