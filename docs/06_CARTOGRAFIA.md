# Servicio cartográfico

Cartography monta la FileGDB en modo solo lectura y mantiene una caché persistente de geometrías simplificadas. Endpoints principales:

- `GET /api/salud`
- `GET /api/referencia/{nivel}`
- `GET /api/geometrias/{nivel}`

Nginx enruta `/api/geometrias/` directamente a cartography. Esto evita transportar geometrías a través del backend estadístico.


## Transferencia optimizada (v32.2)

El servicio precalienta dos representaciones de cada geometría:

- GeoJSON crudo en memoria.
- GeoJSON comprimido con gzip nivel 5.

Cuando el navegador envía `Accept-Encoding: gzip`, cartography entrega la
representación comprimida sin recomprimir en cada petición. La respuesta incluye:

- `X-Geometry-Raw-Bytes`
- `X-Geometry-Transfer-Bytes`
- `X-Geometry-Compression-Pct`
- `Server-Timing`
- `Vary: Accept-Encoding`

El endpoint `/api/salud` expone además métricas de transferencia por nivel.
La caché HTTP sigue siendo versionada mediante ETag y `?v=<firma>`.

Para medir el efecto real a través de Nginx:

```cmd
python scripts\benchmark_cartografia.py --base http://localhost:8010
```
