# Deployment guide (review-first)

This repository does not apply production changes. `firstuser` reviews and executes
site-specific privileged steps; long-running processes use service accounts and no
production code is placed in `firstuser`'s home.

## Preflight

On the target Linux GPU server, capture `scripts/inventory-host.sh`. Confirm three
GPUs, driver/runtime compatibility, cgroup v2, RAM/NVMe safety budgets, MUNGE, Slurm,
DNS/VPN/TLS boundary, and service accounts. Resolve every `REPLACE`, `SET_`, and
commented inventory placeholder before application.

## Reviewed order

1. Review service accounts/groups and `deploy/install-layout.sh --dry-run`.
2. Review `/opt`, `/etc`, `/var/lib`, `/var/log`, `/srv`, and `/scratch` ownership.
3. Merge Slurm snippets, validate controller/daemon configuration, and run 1/2/3-GPU
   diagnostic jobs. Do not preempt non-preemptible research jobs.
4. Build exact llama.cpp and vLLM releases; record source/package and checksums.
5. Install a versioned gateway/harness artifact and create configuration from
   examples. Put secrets in a separate protected environment file.
6. Run Alembic against a backed-up PostgreSQL database.
7. Install systemd/tmpfiles/logrotate definitions, inspect their security properties,
   then enable services in a scheduled window.
8. Register models disabled, benchmark, accept, then enable routing.
9. Execute AT-001–AT-025 and record hardware/runtime versions in compatibility docs.

All supplied scripts default to dry-run or refuse `--apply` until a site-specific hook
has been reviewed. This is intentional: directory ownership, package sources, service
control, QOS, and rollback cannot safely be guessed.

## Network

Backends listen on `127.0.0.1` or Unix sockets. The gateway defaults to loopback.
For LAN/VPN access, use an approved TLS reverse proxy or configure TLS directly,
restrict source networks, and keep backend ports firewalled. Re-run direct-port and
admin-scope security tests after any listener change.
