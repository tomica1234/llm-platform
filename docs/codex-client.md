# Codex client compatibility

Responses is the primary wire API. Merge the following into the user's
`~/.codex/config.toml`; the complete example is
`config/codex/user-config.example.toml`.

```toml
model = "auto"
model_provider = "local_llm_platform"

[model_providers.local_llm_platform]
name = "Local LLM Platform"
base_url = "http://127.0.0.1:8000/v1"
env_key = "LOCAL_LLM_GATEWAY_API_KEY"
wire_api = "responses"
```

Export `LOCAL_LLM_GATEWAY_API_KEY` through the user's protected session environment,
not the TOML. Codex sees only the gateway; llama.cpp and vLLM remain internal.

Use `auto`, `auto/fast`, `auto/balanced`, or `auto/quality` normally. Explicit options
are `prefer/<logical-model>`, `force/<logical-model>`,
`force/<logical-model>@<runtime>`, and `force-deployment/<deployment-id>`. Force never
overrides permissions, safety, or physical capacity and never silently substitutes.

The compatibility fixture verifies unknown benign fields are preserved through the
gateway, request IDs and selected-route headers are returned, and SSE terminates with
`[DONE]`. A real Codex CLI smoke test remains pending until a target model/runtime and
gateway key are provisioned.
