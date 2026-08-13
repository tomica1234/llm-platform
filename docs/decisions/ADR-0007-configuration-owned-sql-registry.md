# ADR-0007: Configuration-owned SQL registry synchronization

- Status: accepted
- Date: 2026-08-13

## Context

Validated YAML defines the desired models and deployments, while PostgreSQL owns
durable foreign-key targets and historical records. An empty SQL registry prevents
skill evaluations from referencing configured models. Deleting rows that disappear
from configuration would invalidate history.

## Decision

Provide `llmctl registry sync`, dry-run by default and mutating only with `--apply`.
The command loads the complete configuration bundle, calculates model and deployment
upserts plus stale-row disables, and applies all changes in one transaction. Missing
rows are retained with `enabled=false`.

Model quality and dynamic skill evidence are not synchronized. Deployment registry
JSON contains only non-secret runtime, resource, serving, capability, and
benchmark metadata; environment values, artifact paths, and executable paths remain
outside SQL. Existing deployment `profile` and `benchmark_id` values are preserved;
new rows use the compatibility profile `configuration` until those fields are managed
by their existing workflows.

## Consequences

Configuration remains the desired registry authority, repeated synchronization is
idempotent, and model/deployment foreign keys remain stable for historical data.
Operators can inspect the exact plan before applying it. Gateway routing, runtime and
Slurm lifecycle, AgentProfiles, and model skill evaluation design are unchanged.
