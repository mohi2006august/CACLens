# CACLens: Brain

> Second brain for this project: concepts, mental models, research, ideas and decisions. Keep it messy and alive.

## 1. Why This Project

CAC is the metric that decides whether growth creates or destroys value. Building it end to end teaches data modelling, attribution and trustworthy analytics.

## 2. Concept Primers

### CAC

Customer Acquisition Cost: total sales and marketing spend ÷ new customers acquired over a period. It is judged against LTV and payback period.

- **Blended vs paid CAC**: All customers vs only those attributed to paid channels.
- **LTV:CAC**: Lifetime value relative to acquisition cost; ~3:1 is a common healthy benchmark.
- **CAC payback**: Months of gross-margin-adjusted revenue needed to recover CAC.
- **Attribution**: Assigning credit to touchpoints (first/last touch, linear, data-driven, MMM).

> **Mental model:** Blended CAC hides channel truth. Always slice by channel, cohort and segment, and include fully loaded costs (salaries, tools).

## 3. What I Want to Learn

- [ ] Attribution models and their biases.
- [ ] Cohort LTV.
- [ ] Semantic layers.
- [ ] LLM-over-metrics safety.

## 4. Reading & Research List

- David Skok, *SaaS Metrics 2.0*
- Christoph Janz, *SaaS Financial Plan*
- Google, *Meridian MMM*
- dbt Semantic Layer docs

## 5. Experiments to Run

| # | Hypothesis | How to test | Result so far |
|---|---|---|---|
| 1 | Position-based vs last-touch changes budget ranking | Compare channel ranking (Attribution screen). | On the demo data the *paid* CAC ranking (Google < Meta < LinkedIn) is stable across all five models, but customer credit moves a lot: Email ranks #8 by new customers under first touch and #1 under last touch. Re-run on real data. |
| 2 | LLM Q&A accuracy with semantic layer vs raw SQL | Eval 100 questions (`uv run caclens eval`). | Offline rule planner: 99/100 on the demo set. Claude run pending an API key (`--planner claude`). No raw-SQL arm: we don't expose SQL to the model at all. |

## 6. Ideas Backlog

- Marketing mix modelling.
- Incrementality test planner.
- Sales-cycle-adjusted CAC.

## 7. Decision Log

| Date | Decision | Reason |
|---|---|---|
| 2026-10-06 | Semantic layer mandatory for Q&A | Prevents metric inconsistency and SQL hallucination. The agent's tools take metric/dimension names from closed enums; values are bound parameters. |
| 2026-10-06 | Marts hold additive measures only; every ratio (CAC, LTV, payback…) lives in `semantic/metrics.yml` | "Every metric defined once." TECHNICAL.md's `channel_cac.sql` sketch computed CAC in SQL; we moved that ratio into the semantic layer instead. |
| 2026-10-06 | Custom Python semantic compiler instead of Cube / dbt Semantic Layer | No new service or paid dependency; the YAML stays close to MetricFlow's shape (simple / ratio / derived, input filters, offsets) so migrating later is mechanical. |
| 2026-10-06 | DuckDB `app` schema for alert state instead of Postgres | Avoids adding a data store for the MVP (CLAUDE.md: ask first). Revisit when alerts need acknowledgement/users. |
| 2026-10-06 | Emails hashed (SHA-256) inside loaders | PII minimised: plaintext never lands in the warehouse; matching still works on hashes and company domains. |
| 2026-10-06 | Identity stitching: CRM id in Stripe metadata > hashed email > company domain; journeys are account based | B2B buyers pay with a billing@ address or a colleague's account; domain matching plus all contacts at the account recovers those journeys. Free-mail domains never match. |
| 2026-10-06 | Spend, clicks and allocated costs are split across segments by each channel's monthly lead mix | Ad platforms don't know a buyer's segment; lead mix is the least-assumption allocation. CAC by segment then differs only through conversion, which is the honest signal. |
| 2026-10-06 | Leads are credited to the touch that created them; customers to the selected attribution model | Funnel counts stay model-independent, and CAC = CPC ÷ (lead CVR × customer CVR) still holds exactly within any slice. |
| 2026-10-06 | Revenue recognised over each invoice's service period; cohort metrics use complete months only | Annual plans would otherwise look like churn for 11 months; a half-finished month looks like mass churn. |
| 2026-10-06 | Content team cost is allocated 70/30 to organic search / email (PRD open question) | Treats organic as a channel with its own fully loaded CAC rather than free. Change the shares in `cost_allocation_rules.csv`. |
| 2026-10-07 | Alerts need a significant Poisson drop in outcomes per dollar, not just a % threshold | 14-day windows of ~15 customers moved ±30% on noise alone; the test cut false alerts from 17 to ~2/year on the demo data. |
| 2026-10-07 | Cost per opportunity is watched as a leading indicator (7-day maturity lag) | Opportunities appear days after a lead, customers weeks after. It flagged the March Meta lead-quality drop on day 7, about three weeks before CAC did. The PRD target is under 3 days; closing that gap needs a shorter window or a lead-quality score at form fill. |
| 2026-10-07 | Publish a serving snapshot only after dbt tests pass | Implements "pause metric publish" from SYSTEM_ARCHITECTURE §9, and readers never lock the file the pipeline writes. |
| 2026-10-07 | Budget optimiser uses power-law response curves shrunk toward elasticity 0.7, bounded to 50–150% of current spend | Spend rarely varies enough to fit elasticities reliably; the prior and the bounds keep recommendations within observed territory. |

## 8. Scratchpad

- _Dump raw thoughts, links and half-formed ideas here._
