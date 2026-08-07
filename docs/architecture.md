# Architecture

## Planes and trust boundaries

```text
user repository ── per-user agent harness ── OpenAI request ──┐
                                                               │
                                             ┌─────────────────▼──────────────┐
                                             │ Gateway / data plane          │
                                             │ auth, normalize, SSE, cancel  │
                                             └─────────────────┬──────────────┘
                                                               │ metadata only
                                             ┌─────────────────▼──────────────┐
                                             │ Control plane                 │
                                             │ router → queue → planner      │
                                             │ desired-state reconciler      │
                                             └───────┬────────────────┬───────┘
                                                     │                │
                                              PostgreSQL         Slurm adapter
                                                                      │
                                             ┌────────────────────────▼───────┐
                                             │ Runtime data plane            │
                                             │ loopback llama.cpp / vLLM     │
                                             └────────────────────────────────┘
```

The user harness alone reads, edits, builds, and tests repositories. The central
gateway receives inference bodies transiently but persists only hashes, sizes, token
counts, task features, route decisions, and outcome metadata by default.

## Two-stage route

1. Parse `auto`, policy, `prefer`, `force`, or `force-deployment`.
2. Remove candidates violating permissions, context/capability, runtime, physical
   capacity, enablement, and confidentiality constraints.
3. For automatic selection, remove unbenchmarked deployments.
4. Rank logical model fitness.
5. Score deployment/resource cost from load state, queue, startup, measured latency,
   GPU use, batching opportunity, continuity, and review diversity.
6. Persist reason codes and forward through the chosen runtime adapter.

Manual force constrains the candidate set before scoring. Empty force sets return an
explicit error; automatic fallback is not permitted.

## Backend lifecycle

```text
STOPPED → ALLOCATING → STARTING → WARMING → READY
                                                │
                                                ▼
                                           DRAINING
                                          /        \
                                   SLEEPING      STOPPING → STOPPED
```

`FAILED`, `DEGRADED`, `ORPHANED`, and `TIMEOUT` are explicit states. A normal profile
transition first stops assigning new requests, waits for `active_requests == 0`, and
then stops or sleeps. The reconciler is idempotent: an already satisfied start/stop
does nothing.

## Balanced to strong-shared sequence

```text
two large-model waiters
  → planner desires strong-shared
  → detect protected non-preemptible jobs (stop if capacity is unavailable)
  → mark existing 2+1 backends draining
  → finish active streams
  → stop backend jobs
  → submit one 3-GPU backend job
  → health + warmup
  → ready and release coalesced requests fairly
```

The scheduler never resizes a live process across GPU counts and never kills a
protected batch job during ordinary rebalancing.

## Restart recovery

PostgreSQL is authoritative for requested and desired state. Slurm and backend health
are observed state. On restart the control plane reconciles database backend records
with Slurm jobs, marks missing jobs failed, identifies orphans, re-evaluates unfinished
requests through idempotency keys, and restores the desired profile before readiness.
