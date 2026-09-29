# Servicio cartográfico

Cartography monta la FileGDB en modo solo lectura y mantiene una caché persistente de geometrías simplificadas. Endpoints principales:

- `GET /api/salud`
- `GET /api/referencia/{nivel}`
- `GET /api/geometrias/{nivel}`

Nginx enruta `/api/geometrias/` directamente a cartography. Esto evita transportar geometrías a través del backend estadístico.
