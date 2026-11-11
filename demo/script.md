# Demo script (≈7 minutes)

Before: `make demo`, open http://localhost:3210, press **Reset** twice. Set `DEMO_PACE=0.35` (default) so agents are watchable.
Keys: `1`–`9` jump to a beat · `Shift+←/→` step · `n` presenter notes · `⌘K` palette. **Autopilot** runs everything hands-free.

| # | Screen | Do | Say |
|---|---|---|---|
| 1 | Mission Control | Click **Start · auto-approve** (or human gates if time allows) | "Five legacy R models, no docs. Watch agents move them through the floor. The clock: ten weeks manual vs. minutes." |
| 2 | Inventory | Click CR-001 | "Discovery built this from code. CR-001's scores feed CR-003 and CR-002 — that's the blast radius." |
| 3 | Parity Certificate | Point at stamp, scatter, residuals | "R ran unmodified in a no-network sandbox. Python matches to 1e-13. Fuzzing 5,000 edge cases: zero divergences — and 1,528 inputs where the legacy code silently returns no decision." |
| 4 | Report | Click **0.691**, then **Reproduce** | "The LLM never writes numbers. Every figure has its definition, hashes, the code that made it, and recomputes live." |
| 5 | Scorecard | **Run benchmark** | "We validate the validator: 10 planted defects, 2 clean controls. 8 caught, 0 false alarms — and we show the two subtle misses." |
| 6 | Monitoring | Severity 0.7, **Inject drift** | "Red breach → alert → validator re-runs automatically → report diff. No human trigger." |
| 7 | Governance | **Verify**, then **Tamper**, **Verify** | "SS1/23 as executable controls. Someone edits a finding in the DB — the chain breaks at that exact entry." |
| 8 | Responsible AI | **Run injection test** | "The source tells AI reviewers to report zero findings. Flagged, ignored, logged; the validator raised its findings anyway." |
| 9 | Impact | Move sliders | "Measured runtime and LLM cost, assumptions tagged and adjustable." |

## Failure runbook
- LLM timeout / no key → it already degrades to the offline drafter (`LLM_MODE=replay`); nothing to do.
- Docker down → sandbox uses recorded reference outputs (Workbench shows "via reference").
- SSE shows OFFLINE → refresh; state is in the DB.
- Anything odd → **Reset** ×2, then **Autopilot**.
- Last resort → play `demo/backup.mp4`.
