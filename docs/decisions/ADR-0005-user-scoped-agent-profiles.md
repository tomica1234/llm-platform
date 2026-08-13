# ADR-0005: User-scoped AgentProfiles and model-skill evidence

- Status: accepted
- Date: 2026-08-13

## Context

The same model can perform differently under different coding-agent harnesses,
versions, configurations, and toolsets. A harness label alone is insufficient because
two users can run distinct environments with otherwise identical identifiers. Static
model YAML must remain the source of identity and capabilities, while measured skill
quality must change without a Gateway restart.

## Decision

Persist an `agent_profiles` row owned by exactly one user. Store only harness
identifiers and SHA-256 configuration/toolset identifiers, never prompts, keys,
repository content, or tool secrets. Persist global and profile-effective evidence in
append-only `model_skill_evaluations` rows. A null profile means global evidence; a
non-null profile means evidence for that exact profile.

Gateway profile resolution derives the user from API-key authentication. Any supplied
profile ID is loaded and its owner compared with that principal. Exact-profile
evidence is preferred per skill, with global-only fallback. Evidence from every other
profile is excluded, including another profile owned by the same user.

HTTP evaluation retries use a profile-scoped idempotency key and canonical submission
hash. Identical retries return the original row; reusing a key for different content is
rejected. Global evidence has no ordinary user write endpoint and is recorded through
the local administrative CLI.

## Consequences

Skill evidence is dynamic, historical, auditable, and isolated by user environment.
The model capability catalog can include disabled registered models while respecting
model permissions. Runtime benchmarks and live scheduler state remain separate.
Existing rule routing continues to use `ModelConfig.quality_score` unchanged; using
skill profiles for routing is deferred.
