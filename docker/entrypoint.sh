#!/usr/bin/env sh
set -eu

cd /app
: "${PORT:=8000}"
: "${CHAMPION_DIR:=outputs/champion_climatology_regional_intensity12}"
: "${PUBLIC_TARGET_PATH:=data/snapshots/inpe_monthly_public_v3/events_target_region.csv}"
: "${PUBLIC_TARGET_SATELLITE:=AQUA_M-T}"
: "${MONTHS:=202608}"
: "${STREAMLIT_PORT:=8501}"
: "${OLLAMA_BASE_URL:=http://ollama:11434}"
: "${OLLAMA_MODEL:=llama3.2:3b}"

case "${1:-api}" in
  api|serve)
    exec python src/production/serving_api.py --model-path "${CHAMPION_DIR}/model.json" --host 0.0.0.0 --port "${PORT}"
    ;;
  streamlit|dashboard)
    exec python -m streamlit run streamlit_app/firecast_dashboard.py --server.port "${STREAMLIT_PORT}" --server.address 0.0.0.0
    ;;
  test)
    exec python -m pytest tests -q
    ;;
  serving-test)
    exec python -m pytest tests/test_serving_api.py tests/test_g6_serving_contract.py tests/test_llm_xai.py -q
    ;;
  data-check)
    exec python scripts/check_data_ingestors.py
    ;;
  plan)
    exec python src/mlops/contracts.py --out outputs/production_ml_plan.json
    ;;
  monthly-plan)
    # shellcheck disable=SC2086
    exec python src/mlops/monthly_ops.py --months ${MONTHS} --out outputs/monthly_operations_plan.json --format json
    ;;
  shadow-score)
    exec python -m src.production.shadow_monitor score --target-path "${PUBLIC_TARGET_PATH}" --target-satellite "${PUBLIC_TARGET_SATELLITE}"
    ;;
  shadow-report)
    exec python -m src.production.shadow_monitor report --target-path "${PUBLIC_TARGET_PATH}" --target-satellite "${PUBLIC_TARGET_SATELLITE}"
    ;;
  predict)
    exec python src/production/champion_climatology.py --out-dir "${CHAMPION_DIR}" --predict --geocodigo "${GEOCODIGO:-2300101}" --ano "${ANO:-2026}" --mes "${MES:-10}"
    ;;
  explain)
    exec python -m src.production.llm_xai --model-path "${CHAMPION_DIR}/model.json" --geocodigo "${GEOCODIGO:-2300101}" --ano "${ANO:-2026}" --mes "${MES:-10}"
    ;;
  xai-graph)
    exec python -m src.production.llm_xai --graph-only --model-path "${CHAMPION_DIR}/model.json" --geocodigo "${GEOCODIGO:-2300101}" --ano "${ANO:-2026}" --mes "${MES:-10}"
    ;;
  bash|sh)
    exec /bin/sh
    ;;
  *)
    exec "$@"
    ;;
esac
