# Operación segura y despliegues

## Respaldo
`scripts\BACKUP.cmd` crea un pg_dump custom y metadatos en `backups/`.

## Actualización transaccional
`scripts\ACTUALIZAR.cmd` exige main y árbol limpio, respalda PostgreSQL,
hace pull --ff-only, valida, construye, despliega, espera healthchecks y ejecuta
smoke test. Si falla, vuelve al commit anterior y restaura PostgreSQL.

## Restauración
```cmd
scripts\RESTAURAR_BACKUP.cmd backups\visor_censo_YYYYMMDD_HHMMSS.dump
```

## Migraciones
El backend ejecuta `backend/db_migrate.py` antes de Uvicorn. Las migraciones
están en `database/migrations/` y su checksum se guarda en
`schema_migrations`. No modificar migraciones ya aplicadas.

## Salud detallada
`GET /api/salud/detallada` verifica PostgreSQL, Ollama, cartografía y Parquet.
`scripts\HEALTH.cmd` devuelve error si un componente está degradado.

## Releases
Los tags `v*` disparan el workflow Release y crean un GitHub Release.
