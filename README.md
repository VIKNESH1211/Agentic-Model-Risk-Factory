# Model Risk Factory

Agentic factory that takes a legacy model estate (messy R scripts, no docs) and produces
**documentation, a Python redevelopment with a parity certificate, an independent validation report
where every number is traceable and reproducible, and live drift monitoring** — under human gates,
with a hash-chained audit ledger. Built from `../build_plan.md`.

## Run it

```bash
git clone https://github.com/VIKNESH1211/Agentic-Model-Risk-Factory.git
cd Agentic-Model-Risk-Factory
cp .env.example .env   # add GROQ_API_KEY (free) or leave LLM_PROVIDER=offline
make setup        # Python 3.11 venv (uv) + npm install
make sandbox      # builds the no-network R image, exports the germancredit dataset
make test         # unit + golden tests
make demo         # builds + starts API :8100 and web :3210, resets state
open http://localhost:3210
make e2e          # scripted check of the whole demo path through the API
```

Ports are 8100/3210 because 8000/3000/3100 were already in use on the dev machine.
No API key is needed: `LLM_PROVIDER=offline` uses deterministic drafters. To use Claude,
set `LLM_PROVIDER=anthropic` and `LLM_API_KEY` in `.env` (see `.env.example`); `make record-llm`
caches responses in `demo/llm_cache/` so the demo replays offline.

## What's real vs. simulated

| Real | Simulated / illustrative |
|---|---|
| Legacy R runs unmodified in Docker (`--network none`, read-only, 1 CPU/1 GB) | Out-of-time sample and drift batches (dataset has no dates) |
| R ↔ Python parity: coefficients Δ ≈ 4e-13, PD Δ ≈ 1e-13, 0/5,000 fuzz divergences | ROI inputs other than measured runtime and LLM cost |
| Fuzzing finds 1,528 inputs where the legacy code returns **no decision** | "Manual baseline ~10 weeks" (assumption, tagged in UI) |
| Seeded-defect benchmark: **8/10 caught, 0/2 false alarms** (2 subtle misses shown) | Controls are our interpretation of SS1/23, not legal advice |
| Every report number is a `{{m:run:metric}}` token; checker rejects raw numbers; Reproduce recomputes | Without an API key, prose is drafted by deterministic templates |
| Hash-chained ledger; tamper is detected at the exact entry | |

## Architecture (backend/app)

- `agents/` Discovery · Documentation · Redevelopment · Validator (independent re-fit) · Red-team · Monitor
- `tools/` deterministic: `sandbox`, `fuzz`, `metrics`, `fairness`, `challenger`, `drift`, `defect_injector`,
  `validation_core` (all pass/fail thresholds), `impact`, `controls`, `graph_build`, `parsers/r_parser`
- `evidence/` `metric_store` (recipes → reproducible numbers), `tokens` (resolver + unsourced-number checker),
  `ledger` (hash chain), `report_builder`
- `orchestrator/pipeline.py` stage graph with human gates persisted in the DB (resume after restart).
  A small hand-rolled equivalent of LangGraph's interrupt/resume — no extra dependency.
- `core/llm.py` Claude adapter (structured JSON output, refusal fallback, cost caps) with live/record/replay cache;
  untrusted files are wrapped as data and pre-scanned for injection.
- API: `api/routes.py` (REST + SSE `/api/events`), contract in `contracts/`.

Frontend (`frontend/`, Next.js 15 + Tailwind 4 + Framer Motion + React Flow + Recharts): Mission Control,
Inventory & graph, Workbench, Parity Certificate, Report + Evidence drawer, Scorecard, Monitoring, Governance,
Responsible AI, Impact, Approvals, ⌘K palette, demo bar (beats 1–9, notes, Autopilot, Reset).

## v2: the whole estate, human-driven pipeline, live traffic

- **All five legacy models** go through the factory. Each legacy R script runs **unmodified** in the sandbox via a harness
  (`backend/app/modelkit/instrument/`) that sources it and exports what parity needs; the data it expects at
  `//shared/riskdata` is mounted from the data room (`var/data_room`).
  | Model | Strategy | Parity |
  |---|---|---|
  | CR-001 PD scorecard | translate + fuzz | coef Δ 3.9e-13, PD Δ 1.1e-13 |
  | PR-001 claims GLM (real dataCar, 67,856 policies) | translate | coef Δ 5.5e-10, freq Δ 6.8e-11 |
  | FR-001 fraud GLM (synthetic ULB-schema data) | translate, R's split pinned | coef Δ 2.1e-9 |
  | CR-003 limit rules (consumes real CR-001 output) | translate | identical |
  | CR-002 random forest (ranger) | rehost (validated as-is) | n/a |
- **Promotion gates between every stage.** Each agent recommends promote/hold; humans decide on the Pipeline board or
  Approvals page, one model or many at once (`POST /api/gates/bulk-decision`). Optional *auto-promote* follows PROMOTE
  recommendations only.
- **Agentic trace.** Every stage: LLM plan (incl. which optional analyses to run) → tool calls with arguments/results →
  findings → LLM recommendation. Stored in `agent_steps`, shown in the Agent Console.
- **State.** Runs checkpoint after every stage; gates, lifecycle, traffic settings and KPI windows persist in SQLite.
  A restart resumes runs and redeploys live models.
- **Live monitoring.** Deployed models score simulated requests one by one (measured latency); outcomes mature after 40s
  (stands in for 12 months). 10-second KPI windows: volume, p50/p95 latency, error/no-decision rate, decision rate,
  score PSI, worst-input CSI, actual/expected, realised Gini/recall. Alert rules need consecutive breaches; a red one
  starts re-validation on the latest live requests. Drift scenarios ramp in gradually.
- **Models Folder** browses the legacy code, the data room and every run's artifacts.

## Scope notes / not built

- FR-001 uses a synthetic stand-in with the Kaggle ULB schema (the real file needs a manual download); CR-003 incomes
  are synthetic. Both are labelled in reports and the UI. SAS/Python legacy models deferred per the plan.
- MLflow is optional (compose profile `mlflow`); metrics live in the app's own metric store.
- SQLite (WAL) instead of Postgres; Playwright replaced by `demo/smoke.py` API-level E2E.
- `backup.mp4` must be screen-recorded by the team.
