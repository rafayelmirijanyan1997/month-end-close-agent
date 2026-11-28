# Evaluation results

Seeds 7, 42, 123; 40 planted errors per seed. Written by `python -m eval.run`.

| approach | recall | precision | correct fixes | seconds per close | tokens per close |
|---|---|---|---|---|---|
| rules | 80% (96/120) | 100% (96/96) | 100% | 0.05 | 0 |
| agent | 38% (45/120) | 98% (45/46) | 84% | 147.15 | 1,066,542 |

## Recall by error type (all seeds)

| approach | duplicate_payment | missing_deposit | transposed_amount | wrong_period | unapproved_vendor |
|---|---|---|---|---|---|
| rules | 24/24 | 24/24 | 24/24 | 0/24 | 24/24 |
| agent | 15/24 | 8/24 | 14/24 | 8/24 | 0/24 |

## Every run

| approach | seed | found | flags | correct flags | correct fixes |
|---|---|---|---|---|---|
| rules | 42 | 32/40 | 32 | 32 | 24/24 |
| agent | 42 | 14/40 | 15 | 14 | 8/14 |
| rules | 7 | 32/40 | 32 | 32 | 24/24 |
| agent | 7 | 31/40 | 31 | 31 | 30/31 |
| rules | 123 | 32/40 | 32 | 32 | 24/24 |
| agent | 123 | 0/40 | 0 | 0 | 0/0 |
