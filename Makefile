.PHONY: help install media sandbox sandbox-stop smoke chaos chaos-long test test-unit test-integration \
        test-e2e test-security lint typecheck secrets audit bench eval profile precommit verify \
        serve demo demo-reset evaluation release-check perf queryplan loadtest \
        jobs live benchmark wrong-cases bandwidth security-scorecard \
        live-evaluation measured-results detection-report daily-live-score \
        rebuild rebuild-check models-validate judge-score live-profile live-profile-anpr \
        live-ingest live-watch benchmark-30 benchmark-50 \
        profile-pipeline benchmark-detectors benchmark-trackers benchmark-ocr \
        live-serve clean

PY := .venv/bin/python
ROOT := $(shell pwd)

help:
	@echo "Saakshya — Gujarat Police Innovation Challenge 2026"
	@echo ""
	@echo "  make install       Create venv and install dependencies"
	@echo "  make media         Render the synthetic camera corpus + ground truth"
	@echo "  make sandbox       Start the local Sentinel Camera Grid replica"
	@echo "  make sandbox-stop  Stop the replica"
	@echo "  make smoke         Verify the ingest contract against live RTSP"
	@echo "  make chaos         2-minute fault-injection run"
	@echo "  make chaos-long    2-hour unattended soak"
	@echo "  make eval          ANPR evaluation against ground truth"
	@echo "  make bench         Compare registry models on identical inputs"
	@echo "  make profile       Print the detected runtime profile and hardware"
	@echo ""
	@echo "  GOVERNMENT FEED   (set CATALOGUE=<url> for the real endpoint)"
	@echo "  make government-profile  Characterise the received cameras"
	@echo "  make government-import   Import the catalogue into the registry"
	@echo "  make government-run      Import, ingest and bootstrap the graph"
	@echo "  make test          Unit + integration tests"
	@echo ""
	@echo "  RUN IT"
	@echo "  make demo          Seed an isolated demonstration store and print tokens"
	@echo "  make serve         Start the API and investigation workspace"
	@echo "  make perf          Measure API p50/p95/p99 against the demo store"
	@echo "  make queryplan     EXPLAIN the hot queries; evidence for every index"
	@echo "  make loadtest      Concurrent camera simulation"
	@echo "  make judge-score   Generate a conservative score from evidence artifacts"
	@echo "  make release-check Everything, from a clean state"
	@echo ""
	@echo "  make live-evaluation PLATE=GJ38BH5815"
	@echo "                     The whole evaluation, end to end, on the live grid"
	@echo "  make daily-live-score"
	@echo "                     Cross-camera marks, long-stay, alerts — film if cross>0"
	@echo ""
	@echo "  make jobs          What holds the machine right now"
	@echo "  make live          CLASS A  live government ingestion (never refused)"
	@echo "  make benchmark     CLASS C  model and VLM benchmarking"
	@echo "                     C and D refuse to start beside a live run;"
	@echo "                     add WAIT=<seconds> to queue instead."
	@echo "  make models-validate  Prove every model actually loads and infers"
	@echo ""
	@echo "  LIVE GOVERNMENT GRID"
	@echo "  make live-profile  Characterise every reachable camera"
	@echo "  make live-ingest   Staged ingest through the real pipeline"
	@echo "  make live-watch    Continuous 30-camera ingest from the registry"
	@echo "  make live-serve    Workspace over the live store"
	@echo "  make rebuild-check Install into a fresh environment and prove it works"
	@echo ""
	@echo "  QUALITY GATES"
	@echo "  make precommit     lint + typecheck + unit tests + secret scan  (fast)"
	@echo "  make verify        precommit + integration + audit + licence     (full)"
	@echo "  make test-e2e      full mandatory chain, end to end"
	@echo "  make lint          ruff"
	@echo "  make typecheck     mypy"

install:
	uv venv --python 3.12
	uv pip install -e ".[dev,analytics]"

media:
	$(PY) tools/sandbox/make_media.py

sandbox: media
	@pkill -f "var/bin/mediamtx" 2>/dev/null || true
	@sleep 1
	@nohup ./var/bin/mediamtx var/mediamtx.yml > var/logs/mediamtx.log 2>&1 &
	@sleep 7
	@curl -s http://127.0.0.1:9997/v3/paths/list | $(PY) -c "import sys,json; d=json.load(sys.stdin); print(f\"grid up: {sum(1 for i in d['items'] if i['ready'])}/{d['itemCount']} paths ready\")"

sandbox-stop:
	@pkill -f "var/bin/mediamtx" 2>/dev/null || true
	@echo "sandbox stopped"

smoke:
	$(PY) tools/sandbox/smoke.py 20

chaos:
	$(PY) tools/chaos/harness.py --minutes 2 --interval 10

chaos-long:
	$(PY) tools/chaos/harness.py --minutes 120 --interval 45 --report var/logs/chaos_soak.json

# --- government feed ------------------------------------------------------
# CATALOGUE defaults to the local replica. Point it at the real endpoint:
#   make government-profile CATALOGUE=http://<host>/api/ingest
CATALOGUE ?= var/media/catalogue.json

government-profile:
	$(PY) tools/data_intake/profile.py --catalogue "$(CATALOGUE)" --sample 12

government-import:
	$(PY) tools/data_intake/import_catalogue.py --catalogue "$(CATALOGUE)"

government-run:
	$(PY) tools/data_intake/import_catalogue.py --catalogue "$(CATALOGUE)" --start --minutes 10

profile:
	@$(PY) -c "from saakshya.runtime import context; print(context().describe())"

eval:
	$(PY) tests/evaluation/run_anpr_eval.py --fps 4

bench:
	$(PY) tools/benchmark_models/run.py --task plate_detect_ocr --fps 2 --include-rejected

profile-pipeline:
	$(PY) tools/profile_pipeline.py

benchmark-detectors:
	$(PY) tools/benchmark_detectors.py

benchmark-trackers:
	$(PY) tools/benchmark_trackers.py

benchmark-ocr:
	$(PY) tools/benchmark_ocr.py --crops "$(OCR_CROPS)" \
	       --ground-truth "$(OCR_GROUND_TRUTH)" --out "$(OCR_REPORT)"

OCR_CROPS ?= var/evaluation/crops
OCR_GROUND_TRUTH ?= evaluation/ground_truth_lite/template.jsonl
OCR_REPORT ?= var/reports/ocr_evaluation.json

test-unit:
	$(PY) -m pytest tests/unit -q

test-integration:
	$(PY) -m pytest tests/integration -q

test-e2e:
	$(PY) -m pytest tests/e2e -q

test:
	$(PY) -m pytest -q

secrets:
	@$(PY) tools/verify/secret_scan.py

audit:
	@$(PY) -m pip_audit --progress-spinner off --skip-editable 2>&1 | tail -5

# Fast gate. Run before every commit.
precommit:
	@echo "── lint ─────────────────────────────────────────"
	@$(PY) -m ruff check src tools tests
	@echo "── typecheck ────────────────────────────────────"
	@$(PY) -m mypy src/saakshya --no-error-summary
	@echo "── unit tests ───────────────────────────────────"
	@$(PY) -m pytest tests/unit -q
	@echo "── secrets ──────────────────────────────────────"
	@$(PY) tools/verify/secret_scan.py
	@echo "PRECOMMIT: PASS"

# ---------------------------------------------------------------------------
# Resource-aware execution
#
# Every heavy job takes a lease first. A live government capture (CLASS A) is
# never refused and never displaced; benchmarking (C) and verification (D)
# refuse to start beside it and say so in a second rather than dying twenty
# minutes in. That is not hypothetical: a twenty-five minute live capture was
# lost exactly that way, killed without a traceback while a VLM benchmark and
# the release gate ran alongside it.
#
#   make jobs            what holds the machine right now
#   make live            CLASS A — live government ingestion
#   make benchmark       CLASS C — model and VLM benchmarking
#   make verify          CLASS D — the standard gate
#   make release-check   CLASS D — everything, from a clean state
#
# Add WAIT=<seconds> to queue behind a job rather than being refused:
#   make release-check WAIT=1800
# ---------------------------------------------------------------------------
RUN_JOB ?= $(PY) tools/run_job.py
#: Directory holding tok_<role>.txt. Never committed.
TOKENS  ?= var/tokens
WAIT    ?= 0

jobs:
	@$(RUN_JOB) --status

# The output report the submission requires: detections with timestamps.
detection-report:
	@$(PY) tools/verify/detection_report.py --db "$(LIVE_DB)" \
	       --out var/reports/detections

# Every number the presentation may use, each traced to the run that produced it.
measured-results:
	@$(PY) tools/verify/measured_results.py --db "$(LIVE_DB)" \
	       --out docs/MEASURED_RESULTS.md

# Whether the live store yet has a cross-camera plate. Film immediately if it does.
daily-live-score:
	@$(PY) tools/verify/daily_live_score.py --db "$(LIVE_DB)" \
	       --json var/reports/daily_live_score.json

# The whole evaluation in one command, for a mark the panel supplies.
#   make live-evaluation PLATE=GJ38BH5815
live-evaluation:
	@$(PY) tools/verify/live_evaluation.py --plate "$(PLATE)" \
	       --db "$(LIVE_DB)" --json var/reports/live_evaluation.json

# Every security property, demonstrated by attempting to violate it.
security-scorecard:
	@$(PY) tools/verify/security_scorecard.py --tokens $(TOKENS) \
	       --json var/reports/security_scorecard.json

# The cases where the right answer is "no". Most testing asks whether a system
# finds what is there; this asks what it does when it should find nothing.
wrong-cases:
	@$(PY) tools/verify/wrong_cases.py --db "$(LIVE_DB)" \
	       --json var/reports/wrong_cases.json

# What metadata-first transport actually saves, measured off the wire.
bandwidth:
	@$(PY) tools/live/bandwidth.py --db "$(LIVE_DB)" \
	       --out var/reports/bandwidth.json

live:
	@$(RUN_JOB) --class A --name live-ingest -- \
	  $(PY) -u tools/live/ingest.py --db "$(LIVE_DB)" \
	        --minutes $(LIVE_MINUTES) $(LIVE_ARGS)

benchmark:
	@$(RUN_JOB) --class C --name benchmark --wait $(WAIT) -- \
	  $(PY) -u tools/benchmark_models/run.py $(BENCH_ARGS)

benchmark-30:
	@$(RUN_JOB) --class C --name benchmark-30 --wait $(WAIT) -- \
	  $(PY) -u tools/benchmark_30.py $(BENCH_ARGS)

benchmark-50:
	@$(RUN_JOB) --class C --name benchmark-50 --wait $(WAIT) -- \
	  $(PY) -u tools/benchmark_50.py $(BENCH_ARGS)

# Full gate. Run before declaring a milestone complete.
verify:
	@$(RUN_JOB) --class D --name verify --wait $(WAIT) -- \
	  $(PY) tools/verify/run_verify.py

lint:
	$(PY) -m ruff check src tools tests

typecheck:
	$(PY) -m mypy src/saakshya

clean:
	rm -rf var/media/*.mp4 var/logs/*.png .pytest_cache .ruff_cache

# --- run it ---------------------------------------------------------------
DEMO_DB    ?= sqlite:///var/demo.db
DEMO_EVID  ?= var/demo_evidence
PORT       ?= 8080

# Demonstration state is deliberately a different database from the evaluation
# store. A demo must never be able to improve a measured result (§44).
demo: media
	$(PY) tools/demo/seed.py --db "$(DEMO_DB)"

demo-reset: media
	$(PY) tools/demo/seed.py --db "$(DEMO_DB)" --reset

serve:
	SAAKSHYA_DB="$(DEMO_DB)" SAAKSHYA_EVIDENCE="$(DEMO_EVID)" \
	SAAKSHYA_MAP_TILES="$${SAAKSHYA_MAP_TILES:-https://tile.openstreetmap.org/{z}/{x}/{y}.png}" \
	SAAKSHYA_MAP_ATTRIBUTION="© OpenStreetMap contributors" \
	$(PY) -m uvicorn saakshya.api.app:build --factory \
	      --host 127.0.0.1 --port $(PORT) --no-access-log --log-level warning

serve-eval:
	SAAKSHYA_DB=sqlite:///var/saakshya.db SAAKSHYA_EVIDENCE=var/evidence \
	$(PY) -m uvicorn saakshya.api.app:build --factory \
	      --host 127.0.0.1 --port $(PORT) --no-access-log --log-level warning

test-security:
	$(PY) -m pytest tests/security -q

# --- live government grid -------------------------------------------------
# RTSP authenticates with SENTINEL_GRID_EMAIL and SENTINEL_GRID_PASSWORD in
# the process environment. The CDN catalogue and HLS sit behind a signed-in
# session: export SENTINEL_GRID_COOKIE (or _TOKEN / _BASIC) for those.
# Never write any of them into a file in this repository.
# See docs/SENTINEL_SANDBOX.md.
LIVE_DB      ?= sqlite:///var/live.db
LIVE_SECONDS ?= 25
LIVE_MINUTES ?= 3

live-profile:
	$(PY) tools/live/profile_grid.py --seconds $(LIVE_SECONDS) --concurrency 5

live-profile-anpr:
	$(PY) tools/live/profile_grid.py --seconds $(LIVE_SECONDS) --concurrency 3 --anpr

live-ingest:
	$(PY) -u tools/live/ingest.py --db "$(LIVE_DB)" --stages 5,10 --minutes $(LIVE_MINUTES)

live-watch:
	$(PY) -u tools/live/ingest.py --db "$(LIVE_DB)" --from-registry --cameras 30 --minutes 0

live-serve:
	SAAKSHYA_DB="$(LIVE_DB)" SAAKSHYA_EVIDENCE=var/live_evidence \
	SAAKSHYA_MAP_TILES="$${SAAKSHYA_MAP_TILES:-https://tile.openstreetmap.org/{z}/{x}/{y}.png}" \
	$(PY) -m uvicorn saakshya.api.app:build --factory \
	      --host 127.0.0.1 --port $(PORT) --no-access-log --log-level warning

# --- model activation -----------------------------------------------------
# A model is not ACTIVE until it has resolved, passed licence policy, loaded
# through the class its task requires, completed a real forward pass, and
# returned output of the right shape. A registry entry is not evidence that a
# model works — that assumption cost this project a detector that had never
# produced a detection.
models-validate:
	$(PY) tools/verify/validate_models.py

# --- measurement ----------------------------------------------------------
perf:
	SAAKSHYA_DB="$(DEMO_DB)" $(PY) tools/perf/api_latency.py --iterations 60

queryplan:
	SAAKSHYA_DB="$(DEMO_DB)" $(PY) tools/perf/query_plans.py

loadtest:
	$(PY) tools/perf/camera_load.py --cameras 50 --seconds 60

judge-score:
	$(PY) tools/judge_score.py

evaluation: media
	$(PY) tests/evaluation/run_anpr_eval.py --fps 4
	$(PY) -m pytest tests/e2e -q

# The gate before declaring a release candidate. Runs from a clean state so a
# hidden machine-local dependency fails here rather than on an evaluator's
# laptop.
release-check:
	@$(RUN_JOB) --class D --name release-check --wait $(WAIT) -- \
	  $(PY) tools/verify/release_check.py

# Non-destructive: installs into a temporary environment and proves the package
# works there. Catches the same machine-local dependencies as a destructive
# rebuild without taking the development environment down, so it actually gets
# run.
rebuild-check:
	$(PY) tools/verify/clean_rebuild.py

# The destructive form, for when the working environment itself is suspect.
rebuild:
	rm -rf .venv var/demo.db var/demo.db-wal var/demo.db-shm var/demo_evidence \
	       .pytest_cache .ruff_cache
	$(MAKE) install
	$(MAKE) verify
