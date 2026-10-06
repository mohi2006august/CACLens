# CLAUDE.md: CACLens

Guidance for Claude Code (and other AI assistants) working in this project.

## Project Summary

Channel-level CAC, LTV:CAC and payback analytics that join ad spend, CRM and billing data, with plain-English Q&A. CACLens pulls spend from ad platforms (Google, Meta, LinkedIn), costs from payroll/tools, leads and deals from CRM (HubSpot/Salesforce) and revenue from Stripe. It builds a unified customer journey table, applies attribution models, and computes fully loaded CAC, LTV, LTV:CAC and payback by channel, segment and cohort. It alerts on CAC spikes and answers questions like 'why did paid social CAC jump in March?'.

## Read First

- `PRD.md`: what we are building and why; requirement IDs (FR-xx) are referenced in commits.
- `SYSTEM_ARCHITECTURE.md`: components, data flow and failure modes.
- `TECHNICAL.md`: stack, data models, APIs and algorithms.
- `DESIGN.md`: UX flows, screens and visual tokens.
- `BRAIN.md`: concept primers, experiments and the decision log.

## Commands

| Command | What it does |
|---|---|
| `uv sync && pnpm i` | Install |
| `dagster dev` | Run pipelines UI |
| `dbt build` | Build models + tests |
| `pnpm dev` | Web app |

## Code Conventions

- Every metric defined once in `semantic/metrics.yml`.
- Keep functions small and typed; no silent `except`. Log with structured fields.
- Every new feature references its FR-ID in the PR description and ships with tests.
- Secrets only come from environment variables. Never hard-code keys or commit `.env`.

## Gotchas

- Time-lag: spend this month acquires customers next month, so support lagged CAC.
- Refunds/chargebacks reduce LTV.

## When Unsure

- Prefer the simplest design that satisfies the PRD; record bigger trade-offs in `BRAIN.md` → Decision Log.
- Run the eval / benchmark suite before claiming a quality or performance improvement.
- Ask before adding a new paid dependency, external service or data store.
