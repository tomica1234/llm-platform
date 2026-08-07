# Local GPU LLM Platform

An OpenAI-compatible gateway and control plane for sharing three NVIDIA GPUs among
up to three coding-agent users. It separates model routing from deployment/resource
selection, exposes Responses as the primary API, retains Chat Completions
compatibility, and keeps repository tools in a per-user harness.

The repository is safe to develop without GPUs or Slurm: fake runtime and Slurm
adapters drive unit, integration, acceptance, and security tests. Real hardware
validation is deliberately opt-in and remains pending until run on the target host.

## Development setup

Python 3.12 or newer is required. `uv` is preferred; the bootstrap script falls back
to the standard library virtual environment and pip.

```bash
./scripts/bootstrap-dev.sh
. .venv/bin/activate
make check
```

Start a development gateway using the example configuration:

```bash
llm-platform --config config/platform.example.yaml
```

Create a development API key without storing its plaintext form:

```bash
LLM_PLATFORM_DATABASE_URL=sqlite+aiosqlite:///./llm-platform.db alembic upgrade head
llmctl key provision alice --config-dir config --apply
```

The provision command generates a random key, stores only its prefix and scrypt hash,
and prints the plaintext once. Change the disabled example user to an explicitly
reviewed active configuration before production provisioning.

Then call `http://127.0.0.1:8000/v1/responses` or
`http://127.0.0.1:8000/v1/chat/completions`. See
`docs/codex-client.md` for Codex configuration.

## Architecture

- Gateway/data plane: authentication, request normalization, streaming proxy.
- Control plane: two-stage routing, fair queue, scheduler, reconciler, persistence.
- Runtime plane: llama.cpp/vLLM adapters behind loopback; Slurm owns resources.
- Tool plane: `agent` executes safe tools as the logged-in user, never centrally.

Design, security, deployment and operations details live in `docs/`. Current phase
and exact verification evidence are in `docs/implementation-status.md`.
