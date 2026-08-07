# Security model

## Trust model

The initial deployment serves two trusted collaborators and at most three users. It
prevents accidents and cross-user disclosure but is not a hostile-tenant sandbox.
Stronger adversarial isolation requires separate login nodes, VMs, or containers.

Principals are OS users, `svc-control`, `svc-llm`, and `svc-models`. Tool execution
runs as the OS user. The control plane has no repository permissions. Slurm/cgroup v2
limits backend GPU, CPU, memory, and processes. Backend ports bind to loopback; only
the gateway may be reachable over LAN/VPN.

## Keys and authorization

- Gateway keys are random per-user values. Only an eight-character lookup prefix and
  scrypt hash are stored; verification uses constant-time digest comparison.
- Records carry scopes, model permissions, concurrency, expiry, and revocation.
- `admin` is a distinct scope and is required for status/control endpoints.
- Backend-internal credentials are separate and never returned to users.
- Rotation means adding a new hash, updating clients, and revoking the old record.

Do not pass secrets on command lines. Keep production secrets in a root-owned 0640
environment file or an approved secret store.

## Data minimization

Central persistence excludes prompt, code, and diff bodies by default. It stores a
canonical body hash and size, token usage, task features, route reasons, and outcome.
Access logs use the same metadata boundary. Debug body capture must be explicit,
time-limited, access-controlled, and audited.

Shared storage may contain reviewed model artifacts, tokenizers, manifests, and
public adapters. Never share writable `HF_HOME`, user tokens, user caches, worktrees,
private datasets, prompt histories, or personal LoRAs.

## Harness controls

The harness resolves all file paths against a real workspace root, rejects absolute
paths, traversal, and symlink targets, limits reads, and requires an explicit
`--in-place` mode before writes. Commands use argument arrays, an allowlist, timeouts,
and no shell. `sudo`, external transport, destructive git operations, and push are
rejected or left for explicit human execution.

## Key threats and mitigations

| Threat | Primary mitigation | Residual risk |
|---|---|---|
| Prompt asks for sudo/push | immutable harness policy and command denylist | manually executed instructions remain human responsibility |
| Cross-user repository access | user-side tools; central service has no repo access | shared Unix groups must be reviewed |
| Backend exposed externally | loopback bind plus host firewall review | incorrect host config can override network intent |
| Key disclosure | hash at rest, redaction, no CLI secrets in production | shell history if admin ignores guidance |
| Malicious model artifact | fixed revision/checksum, license/malware review, disabled-first registration | model formats and runtime parsers remain an attack surface |
| Symlink/path traversal | resolved containment and symlink rejection | hostile filesystems need stronger OS sandboxing |
| Scheduler kills research job | protected non-preemptible awareness | operator emergency stop is intentionally powerful |
| Infinite restart/OOM loop | retry budget, degraded state, circuit breaker | manual diagnosis may still be required |

## Security verification before production

Run `make test-security`, review systemd hardening, validate loopback listeners with
`ss`, verify cgroup device constraints, rotate test credentials, and execute AT-012,
AT-013, AT-014, AT-020, and AT-021 on the target host.
