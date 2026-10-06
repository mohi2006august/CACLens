# CACLens: Technical Specification

> Channel-level CAC, LTV:CAC and payback analytics that join ad spend, CRM and billing data, with plain-English Q&A.
>
> **Concepts:** `CAC`

## 1. Tech Stack

| Layer | Choice | Why |
|---|---|---|
| ELT | Airbyte/dlt + dbt | Standard. |
| Warehouse | DuckDB → BigQuery | Start cheap. |
| Semantic | Cube or dbt Semantic Layer | Metrics as code. |
| App | Next.js + FastAPI | Familiar. |
| LLM | Claude with tool use | Structured queries. |

## 2. Repository Layout

```text
caclens/
├── pipelines/      # dlt sources, dagster jobs
├── dbt/models/     # staging/, journeys/, costs/, cohorts/, marts/
├── semantic/       # metrics.yml
├── api/            # metrics API, qa agent
└── web/
```

## 3. Data Models

```sql
-- marts/channel_cac.sql
select
  period_month,
  channel,
  sum(direct_spend)                          as paid_spend,
  sum(direct_spend + allocated_people_cost
      + allocated_tool_cost)                 as fully_loaded_spend,
  count(distinct new_customer_id)            as new_customers,
  fully_loaded_spend / nullif(new_customers, 0) as cac_fully_loaded
from {{ ref('attributed_costs') }}
group by 1, 2;
```

## 4. API Surface

| Method | Endpoint / Tool | Purpose |
|---|---|---|
| GET | /v1/metrics/cac?by=channel&period=month | CAC series. |
| GET | /v1/metrics/payback?cohort=2026-Q1 | Payback curves. |
| POST | /v1/ask | NL question → answer + chart + query used. |
| GET | /v1/alerts | CAC alerts. |

## 5. Core Algorithms

### Payback

`payback_months = CAC / (ARPA × gross_margin)`. The cohort variant finds the month where cumulative gross-margin revenue per customer ≥ CAC.

### LTV

`LTV = ARPA × gross_margin / monthly_churn`, capped at 5 years, with a cohort-observed variant.

### CAC driver decomposition

`CAC = CPC / (CTR→lead CVR × lead→customer CVR)`. Log-difference decomposition attributes a CAC change to each factor.

## 6. Configuration

| Variable | Purpose |
|---|---|
| GOOGLE_ADS_* | Ads |
| META_TOKEN | Ads |
| HUBSPOT_TOKEN | CRM |
| STRIPE_KEY | Billing |
| WAREHOUSE_URL | Warehouse |

## 7. Testing Strategy

- dbt tests (unique, not null, accepted values, reconciliation to Stripe totals).
- Q&A eval: 100 questions with expected metric queries.

## 8. Performance Budgets

- Dashboard queries < 2s.
- Nightly pipeline < 30 min.

## 9. Local Setup

```bash
uv sync && pnpm i
dagster dev
dbt build
pnpm dev
```
