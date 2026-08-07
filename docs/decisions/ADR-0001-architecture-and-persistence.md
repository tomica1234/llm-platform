# ADR-0001: Modular monolith with adapter and repository boundaries

- Status: Accepted
- Date: 2026-08-07

## Context

The initial service has at most three users but must later split runtime, scheduler,
and persistence responsibilities without exposing user repositories centrally.

## Decision

Use one Python distribution with explicit data-plane, control-plane, runtime, Slurm,
repository, and user-harness packages. All external processes use typed launch specs
and argument arrays. Async SQLAlchemy repositories support PostgreSQL in production
and SQLite in tests. The initial durable queue uses the database, not Redis.

Responses is the primary public protocol; Chat Completions remains an adapter at the
gateway edge. A rule router implements safety constraints and manual force before any
learned router hook.

## Consequences

The deployment is simple for a three-GPU host while retaining seams for later
service extraction. Fake adapters can test lifecycle behavior offline. Database
coordination must be carefully transactional before horizontally scaling.
