# Live demo script (≈ 6 minutes) · the governed lifecycle

Before: `make start`, then `make fresh` (wipes runs, re-onboards the 5 test models). Keep **Auto-promote** off: you play the reviewer.
The recorded film follows the same beats: see `demo/video/out/vo-script.md`.

| # | Screen | Do | Say |
|---|---|---|---|
| 1 | Factory floor `/` | **Start** CR-001 and CR-002 | "Two legacy R models: a scorecard GLM and a ranger random forest. Six agents will work them; I decide at every gate." |
| 2 | Agent console `/agents` | Open CR-001's run, expand `probe_legacy` | "Every step is traced: plan, reasoning, tool call with arguments, result, decision. The R runs unmodified in a no-network, read-only Docker sandbox." |
| 3 | CR-001 → Overview gate | **Review the spec →**, then **Approve** with a comment | "Gate 1. I read the spec the agent drafted; my decision and comment go to the ledger." |
| 4 | CR-001 → Monitoring plan, then Overview | **Send back to the agent**: "add data-quality alerts…" | "The agent chose these KPIs and alert rules. I can steer it in plain language." Show the redraft in the trace (filter `data-quality`). |
| 5 | `/models` | Click CR-001 (blast radius) → **Edit dependencies** → add CR-002 → CR-003 with a reason | "Lineage is inferred from specs and data provenance, correctable by people, and audited." |
| 6 | CR-001 → Parity | Scroll the certificate | "R to Python, proven: every row and coefficient within 1e-6, identical decisions, single-request scoring, fingerprinted." |
| 7 | CR-002 → Parity / Overview | — | "The forest can't be reproduced exactly outside R, so it's rehosted: validated on its R outputs, never deployed." |
| 8 | Report `/reports/…` | Click a number → **Reproduce** | "The LLM never writes a number; every figure is evidence and recomputes live." |
| 9 | CR-001 Overview | **Approve** deploy | "The monitor agent stands up the endpoint and arms the rules it designed." |
| 10 | `/monitoring` | Simulation controls → pick a scenario → severity 1 → **Ramp in** | "Rules go Normal → Pending → Firing; a red rule hands back to the agents: diagnosis, then re-validation on live traffic." |
| 11 | `/approvals` | **Approve** "Accept re-validation" | "A person closes the loop." |
| 12 | `/governance` | **Verify chain** → **Tamper** → **Verify chain** | "Hash-chained: the edited entry is found exactly." |

## If something goes wrong
- A stage ends on HOLD with a blocked gate: that's the guardrail working. Show the trace's **Errors** filter, then **Send back** with guidance or restart the model.
- LLM unavailable → the factory degrades to the offline drafter (`LLM_MODE=replay`).
- Docker down → the sandbox replays recorded reference outputs.
- SSE shows OFFLINE → refresh; state is in the database.
- Last resort → play `demo/video/out/model-risk-factory-voice.mp4`.
