# ADR 0001: Product foundation defaults

- **Status:** Proposed; accepted when Nicholas merges MVP-00
- **Date:** 2026-09-22
- **Decision owner:** Nicholas Bashian
- **Scope:** MVP-01 onward; no application components are created by MVP-00

## Context

The existing Python CLI is reusable, but it cannot by itself provide transactional review state,
resumable jobs, authenticated drafting, or coherent publication generations. The product needs a
small-team architecture that stays inside the stated setup and recurring-cost envelope without
introducing an additional workflow service or frontend build by default.

## Decision

- Use Python 3.13 and Django 5.2 LTS with server-rendered templates and small amounts of plain
  JavaScript. Keep `proposal_ingest` behind application services instead of moving orchestration
  into a model endpoint.
- Use PostgreSQL as the single authoritative application store. JSON/JSONL remain import/export
  formats. Development and concurrency tests use the pinned disposable PostgreSQL container.
- Run one separately deployed Python worker over durable database jobs, leases, heartbeats,
  idempotency keys, and a transactional outbox. Start at concurrency one; do not add Redis or a
  workflow platform without measured need.
- Keep local filesystem/retrieval adapters for development and private S3 plus Bedrock Managed
  Knowledge Base adapters for live use. Eligibility remains application-side.
- Use Microsoft Entra OIDC, server sessions, and an application allowlist. Drafts remain private to
  their creator even when users share corpus access.
- Retain the single-EC2-container deployment as the initial costed candidate, with CloudFormation,
  encrypted persistence, off-host backups, an instance role, and a TLS proxy. MVP-08 must replace
  estimates with measured sizing and can propose a smaller compliant alternative.
- Use no Node build for the initial interface. If a later need is demonstrated, declare and lock the
  modules but install/use them below the owner's `.codex` root, never a synced checkout.

## Consequences

This minimizes services and integration points but accepts single-host downtime for alpha. The
database/worker lifecycle and authorization model must be designed carefully in MVP-01. Deployment,
Managed KB behavior, restore targets, and actual cost remain unverified until their scheduled gates.
Changing one of these defaults requires a short replacement ADR that states acceptance, cost, and
deployment effects.
