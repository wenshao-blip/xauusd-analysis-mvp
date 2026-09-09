---
name: xauusd-session-analyst
description: Analyze XAUUSD from frozen M5/M15/M30/H1 market snapshots and contemporaneous news, produce an auditable conditional plan, and settle prior forecasts. Use for scheduled or manual gold outlooks; never place trades.
---

# XAUUSD Session Analyst

Use only data whose visible timestamp is no later than `data_cutoff`. Reject stale, missing, or internally inconsistent snapshots. Read [schema.md](references/schema.md) before producing or settling a formal prediction.

Evaluate H1 structure first, M30 confirmation second, M15 setup third, and M5 trigger last. Use MACD(12,26,9), Stoch(5,3,3), ADX(14) with +DI/-DI, MA20/60/200, price structure, spread, and the frozen news/event snapshot. News may change risk or confidence but must not override absent price confirmation.

Return exactly one decision: `trade` or `flat`. Give up/range/down probabilities that total 100%, one primary direction, target price range, validity window, execution conditions, and abandonment conditions. If evidence conflicts, data is stale, spread is abnormal, or a high-impact event is too close, choose `flat`.

Before each scheduled prediction, settle the previous prediction at its expiry. Score terminal direction, terminal target-range hit, intraperiod range touch, and Brier score. Keep scheduled and manual predictions separate. Publish calibration only after 20 settled scheduled samples; show sample count and label early results preliminary. Never edit a frozen prediction after observing later prices.

Never call MT5 order functions, request account passwords, expose secrets, or promise profit.

