# FireCast - Makefile
# Reproducible commands for experiments, serving and monthly operations.

.PHONY: all setup reproduce_all clean test lint demo serve-champion status package-champion predict-sample explain-sample production-plan monthly-ops-plan shadow-score shadow-report era5-zonal-status era5-zonal-batch exp05-zonal checkpoint data-check

PYTHON := python3
PIP := pip3
OUTPUT_DIR := outputs
CHAMPION_DIR ?= outputs/champion_climatology_regional_intensity12
PUBLIC_TARGET_PATH ?= data/snapshots/inpe_monthly_public_v3/events_target_region.csv
PUBLIC_TARGET_SATELLITE ?= AQUA_M-T
MONTHS ?= 202608
ZONAL_DIR ?= cache/era5_zonal_fast
ZONAL_PATH ?= $(ZONAL_DIR)/era5_zonal_monthly.csv
WEIGHTS_DIR ?= data/snapshots/era5_grid_weights_v1
MAX_NEW_CELLS ?= 20
WORKERS ?= 1
PAUSE_SECONDS ?= 30
JITTER_SECONDS ?= 10
MAX_429_ATTEMPTS ?= 4
MAX_429_WAIT_TOTAL_SECONDS ?= 180

all: setup reproduce_all

setup:
	$(PIP) install -r requirements.txt
	mkdir -p $(OUTPUT_DIR)

reproduce_all: setup
	@echo "=========================================="
	@echo " FireCast - Full Reproduction"
	@echo "=========================================="
	$(PYTHON) run.py --scope all --experiments all
	@echo ""
	@echo "Outputs saved to $(OUTPUT_DIR)/"
	@echo "Check acceptance_gate_results.csv for pass/fail"

ceara:
	$(PYTHON) run.py --scope ceara --experiments temporal,ablation,forecast

chapada:
	$(PYTHON) run.py --scope chapada_araripe --experiments temporal,ablation,forecast

brazil:
	$(PYTHON) run.py --scope brazil --experiments temporal,state_holdout,ablation,forecast

sanity:
	$(PYTHON) run.py --scope ceara --experiments sanity

baselines:
	$(PYTHON) run.py --scope ceara --experiments baselines

ablation:
	$(PYTHON) run.py --scope all --experiments ablation

forecast:
	$(PYTHON) run.py --scope all --experiments forecast

clean:
	rm -rf $(OUTPUT_DIR)/*.csv
	rm -rf $(OUTPUT_DIR)/*.json
	rm -rf $(OUTPUT_DIR)/*.parquet
	rm -rf $(OUTPUT_DIR)/*.md
	rm -rf __pycache__
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

test:
	$(PYTHON) -m pytest tests/ -v --tb=short

lint:
	flake8 src/ --max-line-length=120 --ignore=E501,W503

demo:
	docker compose up --build

serve-champion:
	PYTHONPATH=. $(PYTHON) src/production/serving_api.py --model-path $(CHAMPION_DIR)/model.json --host 0.0.0.0 --port 8000

status:
	@echo "== Model progress =="
	@sed -n '1,90p' outputs/model_progress_report.md
	@echo ""
	@echo "== Next actions =="
	@sed -n '1,45p' outputs/next_actions.md

package-champion:
	PYTHONPATH=. $(PYTHON) src/production/champion_climatology.py --out-dir $(CHAMPION_DIR)

predict-sample:
	PYTHONPATH=. $(PYTHON) src/production/champion_climatology.py --out-dir $(CHAMPION_DIR) --predict --geocodigo 2300101 --ano 2026 --mes 10

explain-sample:
	PYTHONPATH=. $(PYTHON) -m src.production.llm_xai --model-path $(CHAMPION_DIR)/model.json --geocodigo 2300101 --ano 2026 --mes 10

production-plan:
	PYTHONPATH=. $(PYTHON) src/mlops/contracts.py --out outputs/production_ml_plan.json

monthly-ops-plan:
	PYTHONPATH=. $(PYTHON) src/mlops/monthly_ops.py --months $(MONTHS) --out outputs/monthly_operations_plan.json --format json

shadow-score:
	PYTHONPATH=. $(PYTHON) -m src.production.shadow_monitor score --target-path $(PUBLIC_TARGET_PATH) --target-satellite $(PUBLIC_TARGET_SATELLITE)

shadow-report:
	PYTHONPATH=. $(PYTHON) -m src.production.shadow_monitor report --target-path $(PUBLIC_TARGET_PATH) --target-satellite $(PUBLIC_TARGET_SATELLITE)

era5-zonal-status:
	PYTHONPATH=. $(PYTHON) src/data/ingest_era5_zonal_snapshot.py --report-only --out-dir $(ZONAL_DIR) --weights-dir $(WEIGHTS_DIR)

era5-zonal-batch:
	PYTHONPATH=. $(PYTHON) src/data/ingest_era5_zonal_snapshot.py --out-dir $(ZONAL_DIR) --max-new-cells $(MAX_NEW_CELLS) --workers $(WORKERS) --pause-seconds $(PAUSE_SECONDS) --jitter-seconds $(JITTER_SECONDS) --weights-dir $(WEIGHTS_DIR) --max-429-attempts $(MAX_429_ATTEMPTS) --max-429-wait-total-seconds $(MAX_429_WAIT_TOTAL_SECONDS)

exp05-zonal:
	PYTHONPATH=. $(PYTHON) src/experiments/exp05_era5_zonal_candidate.py --zonal-path $(ZONAL_PATH)

checkpoint:
	$(PYTHON) scripts/checkpoint_harness.py

data-check:
	$(PYTHON) scripts/check_data_ingestors.py
