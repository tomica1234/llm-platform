# Runbook: release rollback and metadata restore

Drain affected services, verify the prior immutable release checksum, review schema
compatibility, atomically repoint `current`, restart through the site service manager,
and verify health/readiness plus one Responses and Chat request. Never remove the
failed release before root-cause analysis.

For restore, recover configuration/DB/manifests/benchmarks/policies from the same
consistent backup set, run config/migration validation, reconcile Slurm and backend
state, detect orphans, re-evaluate unfinished requests, and run acceptance smoke
tests. Record restored revision, backup ID, operator, and verification evidence.
