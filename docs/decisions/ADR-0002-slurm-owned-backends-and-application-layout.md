# ADR-0002: Slurm-owned backends and versioned application layout

- Status: Accepted
- Date: 2026-08-11

## Context

The original templates mixed `/opt/llm-platform/current` and
`/opt/llm-platform/gateway/current`. The reconciler also submitted a Slurm job and
then called the runtime adapter's local process launcher, allowing a second runtime
outside the allocation.

## Decision

Application releases live at `/opt/llm-platform/app/releases/<release>` and the
atomic `/opt/llm-platform/app/current` symlink selects one release environment. That
environment contains the Python package and `llm-platform`, `llm-backend`, `llmctl`,
and `agent` entry points. Runtime installations remain independently versioned under
`/opt/llm-platform/runtimes/{llama.cpp,vllm}/current`.

Only the CLI Slurm adapter starts production backends. It renders an argument-safe
sbatch script, requests execution as `svc-llm`, and invokes `llm-backend` inside the
allocation. Runtime adapters in the control plane attach health/proxy clients to the
loopback endpoint; they never create a local production process. The site must grant
`svc-control` only the narrowly reviewed Slurm submit/cancel authority needed to
manage `svc-llm` jobs.

## Consequences

Gateway upgrades and runtime upgrades can be rolled back independently. There is no
backend systemd unit: systemd owns the Gateway/control plane and Slurm owns every GPU
backend. Startup reconciliation attaches to enabled, known Slurm jobs and reports
unknown or disabled jobs as orphans without cancelling them automatically.
