# CACLens: Product Requirements Document

> Channel-level CAC, LTV:CAC and payback analytics that join ad spend, CRM and billing data, with plain-English Q&A.
>
> **Concepts:** `CAC`

## 1. Overview

CACLens pulls spend from ad platforms (Google, Meta, LinkedIn), costs from payroll/tools, leads and deals from CRM (HubSpot/Salesforce) and revenue from Stripe. It builds a unified customer journey table, applies attribution models, and computes fully loaded CAC, LTV, LTV:CAC and payback by channel, segment and cohort. It alerts on CAC spikes and answers questions like 'why did paid social CAC jump in March?'.

## 2. Problem Statement

Marketing reports platform-reported CPA, finance reports blended CAC, and they never agree. Nobody knows true CAC by channel and cohort including salaries and tools, or which channels pay back fastest, so budgets get allocated on vibes.

## 3. Target Users & Personas

| Persona | Needs |
|---|---|
| Head of growth | Allocate budget to channels with best payback. |
| CFO | Trusted, reconciled CAC for board decks. |
| Founder | Know whether growth is efficient. |

## 4. Goals

- Single source of truth for CAC reconciled with finance.
- Channel-level payback visible.
- Detect CAC regressions within days.

## 5. Non-Goals

- Running ad campaigns.
- Full multi-touch MMM in v1 (planned later).

## 6. User Stories

- As head of growth, I see Google Search CAC $420 (payback 5 mo) vs Meta $910 (payback 14 mo).
- As CFO, I toggle 'fully loaded' to include SDR salaries and tools.
- As founder, I ask 'Which channel's CAC grew most this quarter and why?' and get an answer with the driving metrics.

## 7. Functional Requirements

| ID | Priority | Feature | Description |
|---|---|---|---|
| FR-01 | P0 | Connectors | Google Ads, Meta, LinkedIn, HubSpot/Salesforce, Stripe, payroll CSV. |
| FR-02 | P0 | Unified journey model | Identity stitching (email/domain) from first touch to paid customer. |
| FR-03 | P0 | CAC metrics | Blended, paid, per channel; fully loaded toggle. |
| FR-04 | P0 | LTV & payback | Cohort-based LTV with gross margin; payback months. |
| FR-05 | P1 | Attribution models | First, last, linear, time-decay, position-based; compare. |
| FR-06 | P1 | Alerts | CAC spike detection with decomposition (CPC × 1/CVR …). |
| FR-07 | P1 | NL Q&A | LLM → semantic layer queries (never raw SQL on prod). |
| FR-08 | P2 | Budget optimiser | Marginal CAC curves → recommended reallocation. |

## 8. Non-Functional Requirements

- Daily refresh.
- Metric definitions versioned and documented.
- Reconciles to finance totals within 2%.

## 9. Success Metrics

| Metric | Target |
|---|---|
| Reconciliation gap vs finance | ≤ 2% |
| Budget decisions citing CACLens | Qualitative |
| Alert lead time | < 3 days |

## 10. Release Plan

| Phase | Scope |
|---|---|
| M1 | Spend + CRM + Stripe → blended & channel CAC. |
| M2 | LTV/payback cohorts, fully loaded costs. |
| M3 | Attribution comparisons, alerts. |
| M4 | NL Q&A, budget optimiser. |

## 11. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Identity stitching gaps | Show unattributed share explicitly; improve with UTM hygiene checks. |
| Attribution debates | Show multiple models side by side, not one 'truth'. |

## 12. Open Questions

- Include organic/brand as a channel with allocated content costs?
