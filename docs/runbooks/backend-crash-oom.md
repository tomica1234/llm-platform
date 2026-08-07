# Runbook: backend crash, load failure, or OOM

1. Identify request, deployment, backend instance, and Slurm job IDs.
2. Stop assigning work; preserve active streams if the process remains responsive.
3. Inspect service/backend logs, `sacct`, GPU Xid, VRAM/RAM, and cgroup OOM evidence.
4. Mark the request failed or retryable exactly once according to idempotency policy.
5. Apply retry budget. Repeated load/OOM failure marks deployment `DEGRADED` and opens
   its circuit breaker; do not restart indefinitely.
6. Route automatic work to another eligible benchmarked deployment. Forced work gets
   an explicit unavailable response instead of silent fallback.
7. If a revision caused the regression, drain and use the reviewed rollback workflow.
8. Record root cause, affected IDs, recovery, and benchmark/config correction.
