# Arquitectura de cinco servicios

## Flujo externo

`Navegador -> frontend:80 -> /api/ backend:8000 | /api/geometrias/ cartography:8090`.

Backend consulta los Parquet con DuckDB, persiste estado de aplicación en PostgreSQL y consulta Ollama únicamente cuando las reglas deterministas no resuelven de forma segura la intención. Cartography es el único servicio que monta la FileGDB.

## Principios

- Microdatos y cartografía en solo lectura.
- Un único punto de entrada HTTP: frontend/Nginx.
- Backend sin GDB ni GeoPandas obligatorios.
- Estado temporal fuera de RAM para permitir varios workers.
- LLM separado del cálculo estadístico: interpreta; no calcula resultados oficiales.
- Reglas deterministas tienen prioridad sobre el LLM.
