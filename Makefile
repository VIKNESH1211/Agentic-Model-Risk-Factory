# Model Risk Factory — one-command workflows. Ports: API 8100, web 3210.
API_PORT ?= 8100
WEB_PORT ?= 3210
PY := backend/.venv/bin/python
export NEXT_PUBLIC_API_URL ?= http://localhost:$(API_PORT)

.PHONY: setup sandbox seed dev api web demo test e2e reset-demo record-llm openapi stop

setup:            ## install backend + frontend deps
	cd backend && uv venv --python 3.11 .venv -q && uv pip install --python .venv/bin/python -q -e ".[dev]"
	cd frontend && npm install

sandbox:          ## build the no-network R sandbox image and export the dataset
	docker build -t mrf-rsandbox:latest legacy_models/sandbox
	docker run --rm --entrypoint cat mrf-rsandbox:latest /opt/data/germancredit.csv > data/raw/germancredit.csv

seed: reset-demo  ## fresh DB, controls seeded

api:
	cd backend && .venv/bin/uvicorn app.main:app --port $(API_PORT) --reload

web:
	cd frontend && npx next dev -p $(WEB_PORT)

dev:              ## API (reload) + Next dev server
	$(MAKE) -j2 api web

demo:             ## production build, start both, reset — open http://localhost:3210
	cd frontend && npx next build
	cd backend && (nohup .venv/bin/uvicorn app.main:app --port $(API_PORT) > ../var/api.log 2>&1 &)
	cd frontend && (nohup npx next start -p $(WEB_PORT) > ../var/web.log 2>&1 &)
	sleep 5 && curl -s -XPOST localhost:$(API_PORT)/api/demo/reset && echo && echo "→ http://localhost:$(WEB_PORT)"

stop:
	-pkill -9 -f "uvicorn app.main:app"; pkill -f "next start -p $(WEB_PORT)"; pkill -f next-server; true

test:             ## unit + golden tests (parity, benchmark, ledger, token checker)
	cd backend && .venv/bin/python -m pytest -q

e2e:              ## API smoke test of the full demo path (needs `make demo` running)
	DEMO_API=http://localhost:$(API_PORT) $(PY) demo/smoke.py

reset-demo:
	curl -s -XPOST localhost:$(API_PORT)/api/demo/reset || (cd backend && .venv/bin/python -c "from app.orchestrator.services import reset; reset()")

record-llm:       ## start API against Claude in record mode, run the demo path once, cache responses
	cd backend && (LLM_PROVIDER=anthropic LLM_MODE=record DEMO_PACE=0 nohup .venv/bin/uvicorn app.main:app --port $(API_PORT) > ../var/api-record.log 2>&1 &)
	sleep 5 && DEMO_API=http://localhost:$(API_PORT) $(PY) demo/smoke.py && pkill -f "uvicorn app.main:app"

openapi:
	cd backend && .venv/bin/python -m app.main
