# Model Risk Factory v3 — one-command workflows. Ports: API 8100, web 3210.
API_PORT ?= 8100
WEB_PORT ?= 3210
PY := backend/.venv/bin/python
API := http://localhost:$(API_PORT)
export NEXT_PUBLIC_API_URL ?= $(API)

.PHONY: setup sandbox testdata seed fresh dev api web demo start stop test e2e openapi logs

setup:            ## install backend + frontend deps
	cd backend && uv venv --python 3.11 .venv -q && uv pip install --python .venv/bin/python -q -e ".[dev]"
	cd frontend && npm install

sandbox:          ## build the no-network R sandbox image and export the raw public datasets
	docker build -t mrf-rsandbox:latest legacy_models/sandbox
	docker run --rm --entrypoint cat mrf-rsandbox:latest /opt/data/germancredit.csv > data/raw/germancredit.csv

testdata:         ## (re)generate the test estate's shared drive in legacy_models/_data_room
	$(PY) demo/make_testdata.py

api:
	cd backend && .venv/bin/uvicorn app.main:app --port $(API_PORT) --reload

web:
	cd frontend && npx next dev -p $(WEB_PORT)

dev:              ## API (reload) + Next dev server
	$(MAKE) -j2 api web

start:            ## production build + start API and web in the background (keeps data)
	mkdir -p var/logs
	cd frontend && npx next build
	cd backend && (nohup .venv/bin/uvicorn app.main:app --port $(API_PORT) > ../var/logs/api.out 2>&1 &)
	cd frontend && (nohup npx next start -p $(WEB_PORT) > ../var/logs/web.out 2>&1 &)
	@for i in $$(seq 1 40); do curl -sf $(API)/api/health >/dev/null && break; sleep 1; done
	@echo "→ http://localhost:$(WEB_PORT)"

seed:             ## onboard the 5 test models + data room through the public API
	curl -s -XPOST $(API)/api/demo/seed && echo

fresh:            ## factory reset (wipe DB, runs, store) and re-onboard the test estate
	curl -s -XPOST $(API)/api/demo/reset -H 'content-type: application/json' -d '{"scope":"all","seed":true}' && echo

demo: start fresh ## build, start, fresh state — open http://localhost:3210

stop:
	-pkill -9 -f "uvicorn app.main:app"; pkill -f "next start -p $(WEB_PORT)"; pkill -f next-server; true

logs:             ## follow the platform log
	tail -f var/logs/mrf.log

test:             ## unit + API tests (catalog linter, runtime guardrails, bundle, parity worker, CRUD, API)
	cd backend && .venv/bin/python -m pytest -q

e2e:              ## end-to-end: every test model through the factory via the API (needs `make start`)
	DEMO_API=$(API) $(PY) demo/smoke.py

openapi:
	cd backend && .venv/bin/python -m app.main
