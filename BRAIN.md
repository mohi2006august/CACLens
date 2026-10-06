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

| # | Hypothesis | How to test |
|---|---|---|
| 1 | Position-based vs last-touch changes budget ranking | Compare channel ranking. |
| 2 | LLM Q&A accuracy with semantic layer vs raw SQL | Eval 100 questions. |

## 6. Ideas Backlog

- Marketing mix modelling.
- Incrementality test planner.
- Sales-cycle-adjusted CAC.

## 7. Decision Log

| Date | Decision | Reason |
|---|---|---|
| YYYY-MM-DD | Semantic layer mandatory for Q&A | Prevents metric inconsistency and SQL hallucination. |

## 8. Scratchpad

- _Dump raw thoughts, links and half-formed ideas here._
