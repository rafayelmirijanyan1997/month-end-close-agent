# Evaluation results

Seeds 7, 42, 123; 40 planted errors per seed. Written by `python -m eval.run`.

| approach | recall | precision | correct fixes | seconds per close | tokens per close |
|---|---|---|---|---|---|
| rules | 80% (96/120) | 100% (96/96) | 100% | 0.05 | 0 |
| agent | 48% (57/120) | 97% (58/60) | 85% | 104.04 | 736,582 |
| rules+agent | 100% (120/120) | 100% (120/120) | 100% | 18.38 | 71,593 |

## Recall by error type (all seeds)

| approach | duplicate_payment | missing_deposit | transposed_amount | wrong_period | unapproved_vendor |
|---|---|---|---|---|---|
| rules | 24/24 | 24/24 | 24/24 | 0/24 | 24/24 |
| agent | 24/24 | 8/24 | 13/24 | 8/24 | 4/24 |
| rules+agent | 24/24 | 24/24 | 24/24 | 24/24 | 24/24 |

## Every run

| approach | seed | found | flags | correct flags | correct fixes |
|---|---|---|---|---|---|
| rules | 42 | 32/40 | 32 | 32 | 24/24 |
| agent | 42 | 31/40 | 31 | 31 | 24/31 |
| rules+agent | 42 | 40/40 | 40 | 40 | 32/32 |
| rules | 7 | 32/40 | 32 | 32 | 24/24 |
| agent | 7 | 14/40 | 14 | 14 | 13/14 |
| rules+agent | 7 | 40/40 | 40 | 40 | 32/32 |
| rules | 123 | 32/40 | 32 | 32 | 24/24 |
| agent | 123 | 12/40 | 15 | 13 | 8/8 |
| rules+agent | 123 | 40/40 | 40 | 40 | 32/32 |
