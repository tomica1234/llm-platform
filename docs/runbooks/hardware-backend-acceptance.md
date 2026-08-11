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
