FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY backend/requirements.txt /tmp/requirements.txt
RUN python -m pip install --upgrade pip && python -m pip install -r /tmp/requirements.txt
COPY backend/ /app/backend/
COPY data/ /app/data/
COPY resources/ /app/resources/
COPY database/migrations/ /app/database/migrations/
RUN mkdir -p /app/datos && chmod +x /app/backend/start.sh
WORKDIR /app/backend
EXPOSE 8000
CMD ["/app/backend/start.sh"]
