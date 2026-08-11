# ADR-0003: Validated local Slurm submit helper

- Status: Accepted
- Date: 2026-08-11

## Context

Slurm `--uid` is deprecated and a submission by `svc-control` cannot safely impersonate
`svc-llm`. The initial sbatch template also required the site-specific `agent-service`
QOS even when accounting is intentionally disabled.

## Decision

Production uses a Unix-domain-socket helper running with user `svc-llm`. The socket is
available to group `svc-control` only. Its protocol accepts fixed operations and opaque
deployment/instance or numeric job identifiers; it never accepts an executable, argument
vector, environment, model/config path, output path, or shell command. For a launch, the
helper reloads the reviewed deployment bundle, requires a uniquely enabled deployment,
derives resources and paths, renders the script, and invokes `sbatch` as its own user.
Cancellation uses the same boundary and accepts only a numeric Slurm job ID.

QOS is optional and omitted by default. A site may configure it after SlurmDBD/QOS is
available. A non-production `current_user` mode invokes real `sbatch` directly only when
both configuration and `LLM_PLATFORM_ALLOW_CURRENT_USER_SLURM_SUBMIT=1` opt in.

## Consequences

The Gateway remains `svc-control`; Slurm jobs and backend processes are naturally owned
by `svc-llm`; neither root nor a generic sudo rule is required. The helper has no TCP
listener. Production identity acceptance requires installation of the reviewed unit;
orchestration acceptance can run from a developer checkout without claiming the
production identity boundary was tested.
