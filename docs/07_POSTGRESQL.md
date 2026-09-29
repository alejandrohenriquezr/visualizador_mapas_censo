# PostgreSQL

PostgreSQL desacopla el estado de aplicación del proceso FastAPI. Permite más de un worker sin perder resultados pendientes de feedback o exportación.

El esquema se crea automáticamente en un volumen nuevo mediante `database/init/001_schema.sql`. Para instalaciones existentes no elimine el volumen con `docker compose down -v` salvo que quiera perder el estado.
