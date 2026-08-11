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
5. Install one Python environment at
   `/opt/llm-platform/app/releases/<release>`, atomically point
   `/opt/llm-platform/app/current` to it, and create configuration from examples.
   Keep runtime environments under `/opt/llm-platform/runtimes/*/current`. Put
   secrets in a separate protected environment file.
6. Run Alembic against a backed-up PostgreSQL database.
7. Install systemd/tmpfiles/logrotate definitions, inspect their security properties,
   then enable services in a scheduled window.
8. Register models disabled, benchmark, accept, then enable routing.
9. Execute AT-001–AT-025 and record hardware/runtime versions in compatibility docs.

Do not install or enable a backend runtime systemd service. Separately install the
reviewed backend-submit helper unit: it runs as `svc-llm`, creates no TCP listener, and
grants only `svc-control` access to its fixed-schema Unix socket. Keep `slurm.qos` unset
while accounting storage is `accounting_storage/none`; configure `agent-service` only
after SlurmDBD/QOS is installed and reviewed. Test that production jobs report `svc-llm`.

## Qwen3 0.6B hardware smoke configuration

The example model and `smoke-qwen3-{llama,vllm}-1gpu` deployments are disabled by
default and excluded from automatic production routing. Copy the configuration,
correct the two `/srv/models` artifact paths to the installed site paths, verify the
fixed runtime versions, then explicitly enable the smoke model and only the smoke
deployment being tested. Run:

```bash
LLM_PLATFORM_HARDWARE_TESTS=1 \
LLM_PLATFORM_ALLOW_CURRENT_USER_SLURM_SUBMIT=1 \
LLM_PLATFORM_HARDWARE_CONFIG_DIR=/etc/llm-platform \
make test-hardware
```

The explicit environment opt-in makes this guarded test start each backend through the
orchestrator and real Slurm as the invoking user, verify READY, route a Chat
Completions request, drains/stops it, and confirms
the Slurm job disappeared. Disable the smoke entries again after acceptance. The
smoke result is not a production model benchmark or registration decision.

All supplied scripts default to dry-run or refuse `--apply` until a site-specific hook
has been reviewed. This is intentional: directory ownership, package sources, service
control, QOS, and rollback cannot safely be guessed.

## Network

Backends listen on `127.0.0.1` or Unix sockets. The gateway defaults to loopback.
For LAN/VPN access, use an approved TLS reverse proxy or configure TLS directly,
restrict source networks, and keep backend ports firewalled. Re-run direct-port and
admin-scope security tests after any listener change.
