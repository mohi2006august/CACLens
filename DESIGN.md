# CACLens: Design Document

> Channel-level CAC, LTV:CAC and payback analytics that join ad spend, CRM and billing data, with plain-English Q&A.
>
> **Concepts:** `CAC`

## 1. Design Principles

- Definitions visible everywhere (hover any metric to see its formula).
- Show uncertainty (unattributed %).

## 2. Key User Flows

### Investigate CAC spike

1. Alert: Meta CAC +48%.
2. Open decomposition: CVR lead→customer dropped.
3. Drill to campaigns.
4. Share annotated chart.

## 3. Screens & Surfaces

| Screen | What it shows / does |
|---|---|
| Overview | Blended CAC, LTV:CAC, payback; channel table. |
| Channel detail | Funnel, CAC trend, decomposition. |
| Cohorts | Payback curves by acquisition month. |
| Ask | NL Q&A with chart and query transparency. |

## 4. Wireframe (Primary Screen)

```text
Channel        Spend    Cust   CAC     LTV:CAC  Payback
Google Search  $84k     200    $420    4.8x     5 mo   ▁▂▂▃
Meta Ads       $91k     100    $910    2.1x    14 mo   ▃▄▆█ ⚠
LinkedIn       $40k      32   $1,250   3.4x     9 mo   ▂▂▃▃
Referral       $12k      60    $200    9.9x     2 mo   ▁▁▁▂
[x] Fully loaded   Attribution: [Position-based ▾]
```

## 5. Visual Language

| Token | Value |
|---|---|
| Primary accent | `#3B82F6` (blue) |
| Neutral surface | `#0F1117` dark / `#FAFAF9` light |
| Success / Warning / Danger | `#22C55E` / `#F59E0B` / `#EF4444` |
| Type | Inter for UI, JetBrains Mono for code, tokens and numbers |
| Spacing scale | 4 / 8 / 12 / 16 / 24 / 32 px |
| Radius | 8px cards, 6px inputs, full for pills |

## 6. States

| State | Treatment |
|---|---|
| Unattributed high | Banner: '23% of customers have no source: fix UTMs'. |

## 7. Accessibility

- WCAG 2.2 AA contrast in both themes; never encode meaning with colour alone (pair with icon or label).
- Full keyboard navigation with visible focus rings; `/` focuses search, `?` opens shortcuts.
- Charts ship with a data-table fallback and `aria-describedby` summaries.
- Respect `prefers-reduced-motion`; streaming text is announced politely via `aria-live`.
