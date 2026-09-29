# Modelo de datos

## Microdatos analíticos

DuckDB consulta tres Parquet: personas, hogares y viviendas. Las llaves y variables se describen en `data/diccionario_variables.json`; la geografía en `data/diccionario_geografico.json`.

## Metadatos versionados

`data/` contiene únicamente diccionarios y metadatos pequeños necesarios para interpretar consultas. Los Parquet viven en `datos/` y no se versionan.

## Estado de aplicación

PostgreSQL almacena cache de consultas aprobadas, respuestas asociadas, resultados pendientes usados por feedback/Excel y feedback de usuarios. El esquema está en `database/init/001_schema.sql`.
