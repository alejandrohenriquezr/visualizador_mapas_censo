# Operación Docker

## Primera puesta en marcha

En Windows, completa los datos oficiales indicados en [Instalación y requisitos](00_INSTALACION.md) y ejecuta desde la raíz:

```cmd
INSTALAR.cmd
```

El instalador prepara volúmenes, descarga el modelo configurado y construye los servicios. En Linux o cuando se quiera hacer el proceso manualmente:

```sh
cp .env.example .env
# Edita .env y cambia POSTGRES_PASSWORD antes de iniciar.
docker compose config -q
docker volume create visor_censo_postgres
docker volume create visor_censo_ollama
docker volume create visor_censo_cartography_cache
docker compose up -d db llm cartography
docker compose exec -T llm ollama pull qwen2.5:3b-instruct
docker compose up -d --build backend frontend
docker compose ps
```

Si cambiaste `OLLAMA_MODEL`, descarga ese modelo usando su nombre configurado. El servicio `llm` utiliza Ollama dentro de Docker; no hace falta instalar Ollama en el host. Consulta [Instalación y requisitos](00_INSTALACION.md) para enlaces de Docker e INE y para preparar los datos.

Abra `http://localhost:8010/` (o el puerto configurado en `.env`).

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
