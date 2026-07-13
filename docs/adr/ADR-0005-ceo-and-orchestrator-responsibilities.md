# ADR-0005: ceo-and-orchestrator-responsibilities

## Status
Accepted

## Context
HOS must scale as an AI Company while remaining understandable in one static-site repository.

## Decision
Adopt the v2 architecture rule described by this ADR topic and enforce it in registry, workflow, orchestrator, and tests.

## Consequences
The system gains clear boundaries and local testability. Future external services must integrate through adapters and preserve these contracts.
