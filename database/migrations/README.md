# Migraciones de PostgreSQL

Se ejecutan en orden lexicográfico al iniciar el backend.

- No modificar una migración ya aplicada.
- Agregar cambios como archivos nuevos: 003_..., 004_...
- El SHA-256 queda registrado en schema_migrations.
- Si cambia el checksum de una migración aplicada, el backend no inicia.
