FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends \
    gdal-bin libgdal-dev libgeos-dev libproj-dev proj-data proj-bin \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY cartography/requirements.txt /tmp/requirements.txt
RUN python -m pip install --upgrade pip && python -m pip install -r /tmp/requirements.txt
COPY cartography/ /app/cartography/
RUN mkdir -p /app/cartografia /app/runtime/cache
WORKDIR /app/cartography
EXPOSE 8090
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8090", "--workers", "1"]
