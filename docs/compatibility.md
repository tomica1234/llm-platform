# Compatibility matrix

| Component | Target | Offline evidence | Real-host state |
|---|---|---|---|
| Python | 3.12+ | project metadata; local 3.13 verification | pending target host |
| Responses API | core request + SSE proxy | fake adapter integration tests | Codex CLI pending |
| Chat Completions | core request + SSE proxy | fake adapter integration tests | client smoke pending |
| llama.cpp | GGUF, launch/health/metrics/stream/cancel contract | command and fake contract tests | binary/model/GPU pending |
| vLLM | HF artifact, TP launch/health/metrics/stream/cancel contract | command and fake contract tests | binary/model/GPU pending |
| Slurm | CLI argument-array adapter, GRES job templates | fake three-GPU orchestration tests | MUNGE/cgroup/accounting pending |
| PostgreSQL | SQLAlchemy async schema/repositories | SQLite repository tests | backup/restart/load pending |

No model speed, VRAM/RAM fit, tool parser, chat template, or quality claim is made
before benchmark registration on the actual GPU and runtime revision.
