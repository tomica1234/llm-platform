# Assumptions and unresolved deployment parameters

1. The development implementation targets Python 3.12+; local verification may use
   Python 3.13 when 3.12 is not installed.
2. PostgreSQL is the production database. SQLite is used for isolated development
   and tests through the same repository interfaces.
3. `svc-control` and `svc-llm` may initially share an OS account, while application
   boundaries, credentials, and directories remain distinct.
4. Backend HTTP endpoints bind to loopback. TLS termination and VPN routing are
   deployment-specific and are not guessed by the application.
5. Model names, artifacts, runtime versions, GPU counts, memory budgets, chat
   templates, and performance values are registry data. Example deployments remain
   disabled for automatic routing until a benchmark is registered.
6. This development host is macOS without detected NVIDIA/Slurm tools. Fake adapters
   are authoritative only for software contracts; Linux/GPU/Slurm acceptance remains
   pending on the target server.
7. Real API keys are provisioned out-of-band. Examples contain no accepted default
   credential.
8. Queue persistence captures request metadata and hashes, never prompt/code bodies.
