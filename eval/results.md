# Evaluation results

Seeds 7, 42, 123; 40 planted errors per seed. Written by `python -m eval.run`.

| approach | recall | precision | correct fixes | seconds per close |
|---|---|---|---|---|
| rules | 80% (96/120) | 100% (96/96) | 100% | 0.03 |

## Recall by error type (all seeds)

| approach | duplicate_payment | missing_deposit | transposed_amount | wrong_period | unapproved_vendor |
|---|---|---|---|---|---|
| rules | 24/24 | 24/24 | 24/24 | 0/24 | 24/24 |

## Every run

| approach | seed | found | flags | correct flags | correct fixes |
|---|---|---|---|---|---|
| rules | 42 | 32/40 | 32 | 32 | 24/24 |
| rules | 7 | 32/40 | 32 | 32 | 24/24 |
| rules | 123 | 32/40 | 32 | 32 | 24/24 |
