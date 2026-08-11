# Runbook: Slurm backend hardware acceptance

1. Copy the example configuration to a review directory. Correct the installed
   Qwen3-0.6B HF/GGUF paths, then enable the smoke model and one smoke deployment.
2. Confirm no production request is using the smoke ports and no unrelated GPU job
   would be preempted. Keep all production model placeholders disabled.
3. Run the guarded hardware test command from `docs/deployment.md` as the same
   control-plane identity used by the Gateway.
4. For each backend, retain the test output, Slurm job/accounting ID, effective
   `svc-llm` owner, READY transition, routed response, and post-cancel `squeue` result.
5. If startup fails, inspect Slurm accounting and backend stderr by instance/job ID.
   Do not launch the runtime directly to bypass Slurm. Follow
   `backend-crash-oom.md` for failure-budget and OOM handling.
6. Disable both smoke deployments and the smoke model after the test. These artifacts
   must never become benchmark-eligible production routes.

On Gateway restart, check `/admin/status` and compare registered deployment IDs with
`squeue --user svc-llm`. Known healthy jobs should be reattached. Investigate unknown
jobs as orphans; do not cancel them until ownership and active requests are known.

## Acceptance layers

For orchestration acceptance from the `shunta` checkout, use a reviewed non-production
config with `slurm.qos: null`, then explicitly export
`LLM_PLATFORM_ALLOW_CURRENT_USER_SLURM_SUBMIT=1`. The guarded hardware test selects
current-user mode for that process. This runs real `sbatch`, Slurm, and the real runtime
as `shunta`; it does not claim production identity acceptance.

After the reviewed `llm-platform-backend-submit.service` is installed, use production
configuration with `submission_mode: helper`. Verify the chain `svc-control` → restricted
Unix socket → helper running as `svc-llm` → Slurm job owned by `svc-llm`.

To rerun only llama.cpp orchestration acceptance from `shunta`:

```bash
LLM_PLATFORM_HARDWARE_TESTS=1 \
LLM_PLATFORM_ALLOW_CURRENT_USER_SLURM_SUBMIT=1 \
LLM_PLATFORM_HARDWARE_CONFIG_DIR=/absolute/path/to/reviewed-smoke-config \
.venv/bin/python -m pytest -m hardware tests/acceptance/test_real_hardware.py -k 'orchestrator_gateway_backend_and_gpu_release and llama_cpp' -vv
```

Submission assertion failures include the helper or `sbatch` stderr in the test output.
