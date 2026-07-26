# syntax=docker/dockerfile:1
FROM python:3.10-slim AS runtime

LABEL org.opencontainers.image.title="FireCast"
LABEL org.opencontainers.image.description="Fail-closed FireCast champion API and operational ML tasks"
LABEL org.opencontainers.image.source="firecast"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    STREAMLIT_PORT=8501 \
    OLLAMA_BASE_URL=http://ollama:11434 \
    OLLAMA_MODEL=llama3.2:3b \
    CHAMPION_DIR=outputs/champion_climatology_regional_intensity12 \
    PUBLIC_TARGET_PATH=data/snapshots/inpe_monthly_public_v3/events_target_region.csv \
    PUBLIC_TARGET_SATELLITE=AQUA_M-T

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.txt

COPY . ./

RUN python -m py_compile \
      src/production/serving_api.py \
      src/production/champion_climatology.py \
      src/production/shadow_monitor.py \
      src/production/llm_xai.py \
      streamlit_app/firecast_dashboard.py \
      src/mlops/contracts.py \
      src/mlops/monthly_ops.py

EXPOSE 8000 8501

ENTRYPOINT ["/bin/sh", "/app/docker/entrypoint.sh"]
CMD ["api"]
