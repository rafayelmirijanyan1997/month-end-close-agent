# Evaluation results

Seeds 7, 42, 123; 40 planted errors per seed. Written by `python -m eval.run`.

| approach | recall | precision | correct fixes | seconds per close | tokens per close |
|---|---|---|---|---|---|
| rules | 80% (96/120) | 100% (96/96) | 100% | 0.06 | 0 |
| agent | 44% (53/120) | 91% (53/58) | 85% | 260.46 | 2,073,844 |

## Recall by error type (all seeds)

| approach | duplicate_payment | missing_deposit | transposed_amount | wrong_period | unapproved_vendor |
|---|---|---|---|---|---|
| rules | 24/24 | 24/24 | 24/24 | 0/24 | 24/24 |
| agent | 19/24 | 8/24 | 18/24 | 8/24 | 0/24 |

## Every run

| approach | seed | found | flags | correct flags | correct fixes |
|---|---|---|---|---|---|
| rules | 42 | 32/40 | 32 | 32 | 24/24 |
| agent | 42 | 8/40 | 9 | 8 | 7/8 |
| rules | 7 | 32/40 | 32 | 32 | 24/24 |
| agent | 7 | 15/40 | 15 | 15 | 12/15 |
| rules | 123 | 32/40 | 32 | 32 | 24/24 |
| agent | 123 | 30/40 | 34 | 30 | 26/30 |
