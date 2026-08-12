# ADR-0004: Four-tier virtual-model policies

## Status

Accepted

## Context

The original automatic routing API exposed fast, balanced, and quality variants.
It lacked a distinct highest-quality tier, and the name `quality` did not clearly
separate quality-first routing from maximum-quality escalation and final review.
Virtual policy names must remain separate from registered model IDs.

## Decision

The canonical public policies are `fast`, `balanced`, `strong`, and `max`, with
`auto` retaining balanced as its base policy. Both bare policy names and
`auto/<policy>` forms select automatic routing. `quality` and `auto/quality` are
accepted as compatibility aliases that normalize to `strong`; routing configuration
contains no `quality` key.

Fast emphasizes latency, wait, loaded state, batching, switching, and resource cost.
Balanced retains the normal tradeoff. Strong increases quality influence while still
accounting for operational cost. Max makes quality dominant and operational penalties
small. Permissions, capabilities, context, capacity, eligibility, failure escalation,
and high-risk review remain independent routing constraints or signals. Explicit
prefer and force selectors retain their existing behavior.

## Consequences

Clients can request four stable policy levels without confusing policies with model
registrations. Old quality selectors continue to work, while old three-key routing
files must be migrated to the exact four canonical keys. Intent dimensions such as
coding, review, and debug are deliberately deferred.
