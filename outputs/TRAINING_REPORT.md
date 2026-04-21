# Veridict Training Report

Generated: 2026-04-21T12:39:37
Base model: `google/gemma-3-27b-it`
Total wall-clock: 1259.7 min

## Metrics

| Model | Status | Valid JSON | Issue Type Acc | Severity Acc | Golden Issue Acc | Elapsed (min) |
|-------|--------|-----------:|---------------:|-------------:|-----------------:|--------------:|
| harvey | ERROR | — | — | — | — | — |
| kira | ERROR | — | — | — | — | — |
| admin | ERROR | — | — | — | — | — |

## Adapter checkpoints

- [ ] `C:\Users\hac23\PycharmProjects\Veridict\outputs\harvey_adapter`
- [ ] `C:\Users\hac23\PycharmProjects\Veridict\outputs\kira_adapter`
- [ ] `C:\Users\hac23\PycharmProjects\Veridict\outputs\admin_adapter`

## Files

- Run state: `C:\Users\hac23\PycharmProjects\Veridict\outputs\run_state.json`
- Full log: `C:\Users\hac23\PycharmProjects\Veridict\outputs\training_run.log`

## Next step

Wire the adapters into `app/backend/agents/reviewer.py` and `app/backend/agents/admin.py`.