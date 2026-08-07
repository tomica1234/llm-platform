# Operations

## Routine status

```bash
llmctl status
llmctl config validate --config-dir /etc/llm-platform
llmctl profile show --config-dir /etc/llm-platform
squeue --name 'llm-*'
sacct --starttime today
```

Correlate gateway request ID → route decision → backend instance ID → Slurm job ID.
Do not expose another user's prompt, repository name, or code in status output.

## Operating modes

- `auto`: router/reconciler operate normally.
- `fixed-profile`: retain an operator-selected reviewed profile.
- `drain`: reject new work and finish active requests.
- `maintenance`: stop inference backends after drain.
- `safe-mode`: disable switching and use one reviewed fallback deployment.

Profile changes respect dwell time, coalescing, switch-rate limit, active streams, and
protected jobs. Emergency cancellation is an administrator action and must list
affected request IDs before confirmation.

## Add or update a model

1. Fix upstream revision and license; acquire as `svc-models` through an approved
   process, not from an API request.
2. Verify checksum and scan artifact structure.
3. Add a disabled model/deployment manifest.
4. Benchmark candidate 1/2/3-GPU profiles and record hardware/runtime revision.
5. Validate tool calls, structured output, context, streaming, concurrency, memory.
6. Review results, enable deployment, then add it to automatic routing.

Disk pressure stops new acquisition before it deletes registered artifacts. Garbage
collection must follow registry references; custom quantization, LoRA, benchmark and
manifest data require backup.

## Release and rollback

Releases live in version directories with checksums and a `current` symlink. Validate
config and migrations, drain, switch atomically, restart, health-check, and retain the
previous version. `scripts/deploy-release.sh` and `scripts/rollback-release.sh` are
dry-run templates and deliberately do not invoke privileged service management.

## Backup and restore

Back up configuration, PostgreSQL, manifests, benchmarks, route policy, release
manifests, custom artifacts, unit templates, Slurm config, and runbooks. Exclude
secrets from ordinary archives and use an approved encrypted secret backup. A restore
is not complete until config validation, DB migration status, Slurm reconciliation,
orphan detection, backend health, and a request smoke test all pass.
