# Runbook: disk pressure, GPU Xid, or driver fault

## Disk pressure

Stop model downloads and benchmark artifact creation. Do not blindly delete model
paths. Identify registry references, rotate/compress logs, expire approved transient
cache, and move only unreferenced artifacts after checksum/backup review. Verify DB,
model manifests, and free-space alerts before resuming.

## GPU Xid/driver fault

Enter drain or maintenance, list affected request/job IDs, and preserve diagnostics.
Do not reset GPUs or update drivers from application automation. An administrator
follows the vendor/site procedure, then validates three GPUs, Slurm GRES/cgroup,
1/2/3-GPU test jobs, backend health, and acceptance smoke tests before leaving
maintenance.
