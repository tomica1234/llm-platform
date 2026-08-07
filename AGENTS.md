# Contributor instructions

## Purpose and boundaries

This repository implements the GPU coding-agent platform specified in
`docs/requirements.md`. The central control plane owns inference routing, queueing,
backend lifecycle, and GPU allocation. It must not read or write user repositories.
Only the per-user agent harness may operate on a repository, under that user's OS
identity and inside an explicitly allowed workspace.

Keep data, control, and tool-execution planes separate. API keys authenticate a
principal; they never identify a model. Keep llama.cpp, vLLM, Slurm, and future
provider behavior behind adapters.

## Safety rules

- Never run sudo, push Git changes, inspect secrets, or apply host/service config.
- Never write to production paths such as `/etc`, `/opt`, `/srv`, `/var/lib`, or
  `/scratch` while developing. Produce reviewed templates and dry-run scripts.
- Do not use `shell=True` or concatenate untrusted values into shell commands.
- Do not centrally log prompt bodies, source code, diffs, API keys, or tokens.
- Do not silently fall back when a user forces a model/runtime/deployment.
- Do not claim real GPU, Slurm, llama.cpp, or vLLM verification without evidence.

## Commands

```bash
make bootstrap
make format
make lint
make typecheck
make test
make test-integration
make test-security
make check
```

Tests must run without GPUs, Slurm, external services, or network access unless
explicitly marked `hardware`.

## Definition of done

A change is complete only when code, tests, documentation, configuration examples,
`docs/requirements-traceability.md`, and any architectural decision record agree.
Update `docs/implementation-status.md` with commands actually run and their results.
Requirements changes require a traceability update and an ADR. Keep this file below
32 KiB and refer to the authoritative requirements rather than duplicating them.
