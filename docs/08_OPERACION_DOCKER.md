# Operación Docker

## Primera puesta en marcha

```cmd
copy .env.example .env
docker compose up -d db llm cartography
scripts\PULL_LLM.cmd
docker compose up -d --build backend frontend
docker compose ps
scripts\SMOKE_TEST.cmd
```

## Logs

```cmd
scripts\LOGS.cmd
```

## Reinicio

```cmd
docker compose restart backend frontend
```

## Actualización de código

```cmd
git pull
docker compose up -d --build
```

No use `down -v` en operación normal.
