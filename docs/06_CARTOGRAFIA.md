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


## Simplificación por nivel (v32.3)

La tolerancia puede configurarse de forma independiente para región, provincia y comuna:

- `CENSO_SIMPLIFICACION_REGION`
- `CENSO_SIMPLIFICACION_PROVINCIA`
- `CENSO_SIMPLIFICACION_COMUNA`

Si una variable específica no está definida, se usa `CENSO_SIMPLIFICACION`.
La firma de caché incluye la tolerancia del nivel, por lo que cambiarla invalida
automáticamente solo la geometría correspondiente.

Antes de adoptar valores más agresivos se recomienda medir tamaño y error geométrico:

```cmd
python scripts\benchmark_simplificacion.py
```

El benchmark se ejecuta dentro del contenedor cartography y compara varias
tolerancias usando la FileGDB real. Reporta cantidad de coordenadas, tamaños
GeoJSON/gzip, reducción de vértices, error de área total y máximo, geometrías
inválidas y tiempo de proceso.
