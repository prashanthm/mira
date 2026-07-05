---
title: Engineering Handbook
owner: platform
---

# Engineering Handbook

Reference notes for the demo research corpus.

## Middleware Ordering

Every request flows through one ordered chokepoint: auth, correlation,
entitlement, guardrail-in, handler, guardrail-out, telemetry (ADR-009).
Stages are onion-bound so guardrail-out also covers the streaming error path.

## Deployment Profiles

One artifact runs everywhere; a profile is a named default-set for the
independent axes (platform, model endpoint, MCP endpoint, auth mode), each
still overridable by env (ADR-047).

## Testing Standards

Tests run fully offline against the local echo provider. Every module has a
matching test file; CI gates on import-boundary lint plus the pytest suite.
