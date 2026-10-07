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
| 3 | A form-fill lead-quality signal gets alert lead time under 3 days | `uv run caclens alerts-backtest` (replays the detector over history vs `evals/alert_incidents.yml`). | Confirmed on the demo data. Same data, before → after: lead time 12 → 2 days, false alarms 1.93 → 0.21 per channel-year. With point-in-time scores and the strict CAC backstop, four demo seeds give 1, 1, 2, 2 days and 0.21–0.43 false alarms per channel-year. Needs validating on real incidents (`alerts-backtest --suggest`). |

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
| 2026-10-07 | Alerts need a significant drop in outcomes per dollar, not just a % threshold | 14-day windows of ~15 customers moved ±30% on noise alone; a significance test cut false alerts from 17 to ~2/year on the demo data. |
| 2026-10-07 | Early warning on cost per qualified lead (3-day window vs the prior 28, p < 0.001) | PRD target: alert lead time < 3 days. Outcome-based signals cannot get there: at ~25 Meta leads/day, even opportunities need ~6+ days of data to show a significant drop, and they arrive 1–7 days after the lead. Lead quality is known at form fill (CRM lead score, else work email + known company size), so it moves the day a bad audience starts. Backtest: 12 → 2 days. |
| 2026-10-07 | Dropped the cost-per-opportunity alert (the metric stays in dashboards and Q&A) | After the qualified-lead alert existed it fired ~10 days later and caused most false alarms (spend and opportunities land in different weeks). |
| 2026-10-07 | Negative-binomial test with dispersion measured on same-length windows over the prior half year; CAC alerts need 3 flagged days; alerts stay open until cost recovers against the baseline they fired on | Window totals are over-dispersed (weekday mix, budget changes, lag between spend and outcomes), so a Poisson test over-alerts. A daily scan of overlapping windows crosses p < 0.01 by chance on single days; real regressions persist. A 28-day baseline absorbs a lasting regression within weeks, so "no longer flagged" must not mean "fixed". |
| 2026-10-07 | Qualify leads on the score they had at lead time (48h grace), never today's score; fall back to the fit rule | CRMs re-score leads after a deal closes, so the current score leaks the outcome. On the demo data, today's score makes unqualified leads convert at 0.18% vs 12.2% for qualified (a near-perfect, fake separation); point in time gives the honest 2.3% vs 9.4%. History comes from HubSpot `propertiesWithHistory`, Salesforce `LeadHistory` (if field tracking is on) and a snapshot per load in `raw.crm_score_history`. |
| 2026-10-07 | CAC alert is a strict backstop (p < 0.001, 3 flagged days) | Across four seeds it never confirmed the Meta incident in time (~12 Meta customers per 14-day window is too few) yet caused most false alarms (one seed hit 1.07/channel-year). Tightening halves false alarms (0.54 → 0.27 across seeds) and keeps it for large sustained regressions lead quality can't show. A sales-side incident in the demo would let us measure its sensitivity; not built yet. |
| 2026-10-07 | `alerts-backtest --suggest` mines history for candidate incidents | Labelling real incidents is the only way to validate alerts on real data; candidates turn it into a confirm/reject task. On the demo it finds the Meta incident plus a few low-volume LinkedIn months, which is why a human confirms. |
| 2026-10-07 | Demo leads have a latent fit (good/poor) with noisy CRM proxies (score, work email) | Makes lead quality observable the way it is in real CRMs, imperfectly (~93% of good fits and ~16% of poor fits qualify), so the early warning is tested against signal and noise rather than a perfect label. |
| 2026-10-07 | Publish a serving snapshot only after dbt tests pass | Implements "pause metric publish" from SYSTEM_ARCHITECTURE §9, and readers never lock the file the pipeline writes. |
| 2026-10-07 | Budget optimiser uses power-law response curves shrunk toward elasticity 0.7, bounded to 50–150% of current spend | Spend rarely varies enough to fit elasticities reliably; the prior and the bounds keep recommendations within observed territory. |

## 8. Scratchpad

- _Dump raw thoughts, links and half-formed ideas here._
