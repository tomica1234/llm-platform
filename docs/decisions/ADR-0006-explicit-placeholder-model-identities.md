# ADR-0006: Explicit placeholder identities in example configuration

- Status: accepted
- Date: 2026-08-13

## Context

Example configuration used vendor-like model identifiers and metadata that could be
mistaken for registered production models when exposed through
`/v1/model-capabilities`. Model characteristics are evaluated dynamically and can
vary by AgentProfile, so examples must not imply unmeasured skills or stable roles.

## Decision

Use `example-model-a` and `example-model-b` as disabled, unconfigured placeholder
identities. Their display names and `placeholder` family make that status explicit,
and their model records contain no asserted skill scores or role tags. Use matching
`example-a-*` and `example-b-*` deployment identifiers throughout templates,
documentation, fixtures, and selector examples.

Keep `qwen3-0.6b-smoke` unchanged because it identifies a real installed smoke-test
artifact. This identity-only cleanup does not change AgentProfile data, dynamic skill
evaluations, routing policy behavior, Slurm, or runtime architecture.

## Consequences

Example metadata cannot be confused with a real candidate registration, while sites
must replace placeholder identity, artifact, capability, and benchmark data before
enabling a deployment. Existing examples retain their structural coverage without
claiming model skills.
