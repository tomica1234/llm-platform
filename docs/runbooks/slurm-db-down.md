# Runbook: Slurm or database unavailable

## Slurm

Freeze profile switching and backend submission. Do not cancel non-preemptible jobs.
Observe existing backends without assuming Slurm state. Restore MUNGE/controller/
daemon through site procedures, compare DB backend IDs to `squeue`/`sacct`, mark
missing jobs failed, identify orphans, and reconcile only after accounting is stable.

## PostgreSQL

Fail readiness and stop accepting state-changing inference work; do not execute a
request without durable idempotency state. Preserve existing streams if their state
can be finalized safely. Restore the backed-up database, validate migrations, compare
backend records to Slurm, recover queued work, resolve `running` requests explicitly,
and only then restore readiness.
