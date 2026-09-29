import gzip, json, sys, urllib.request

base=(sys.argv[1] if len(sys.argv)>1 else "http://localhost:8010").rstrip("/")

def _headers_normalizados(headers):
    return {str(k).lower(): str(v) for k, v in headers.items()}

def get(path, timeout=300, headers=None):
    req=urllib.request.Request(base+path,headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read(), _headers_normalizados(r.headers)

status,body,_=get("/api/salud",30)
assert status==200
print("OK backend /api/salud")

status,body,_=get("/api/salud/detallada",30)
assert status==200
health=json.loads(body)
assert health.get("estado")=="ok",health
print("OK salud detallada",",".join(sorted(health.get("componentes",{}).keys())))

status,encoded,headers=get(
    "/api/geometrias/region",
    300,
    {"Accept":"application/geo+json","Accept-Encoding":"gzip"},
)
assert status==200
content_encoding=headers.get("content-encoding","").lower()
if content_encoding!="gzip":
    raise AssertionError(
        "La cartografía no llegó comprimida con gzip. "
        f"content-encoding={content_encoding!r}; headers={headers}"
    )
body=gzip.decompress(encoded)
if len(body)<=1000:
    raise AssertionError(f"GeoJSON regional inesperadamente pequeño: {len(body)} bytes")
if len(encoded)>=len(body):
    raise AssertionError(
        f"gzip no redujo el tamaño: transfer={len(encoded)} raw={len(body)}"
    )

raw_header=int(headers.get("x-geometry-raw-bytes",len(body)))
transfer_header=int(headers.get("x-geometry-transfer-bytes",len(encoded)))
if raw_header!=len(body):
    raise AssertionError(
        f"X-Geometry-Raw-Bytes inconsistente: header={raw_header} real={len(body)}"
    )
if transfer_header!=len(encoded):
    raise AssertionError(
        f"X-Geometry-Transfer-Bytes inconsistente: header={transfer_header} real={len(encoded)}"
    )

print(
    "OK cartografia region",
    f"transfer={len(encoded)} bytes",
    f"raw={len(body)} bytes",
    f"compresion={headers.get('x-geometry-compression-pct','n/a')}%"
)

status,body,_=get("/",30)
assert status==200 and b"html" in body.lower()
print("OK frontend /")

req=urllib.request.Request(
    base+"/api/consulta/progreso",
    data=json.dumps({"pregunta":"cantidad de poblacion por region"}).encode(),
    headers={"Content-Type":"application/json"},
    method="POST",
)
with urllib.request.urlopen(req,timeout=300) as r:
    payload=r.read()
assert b"resultado" in payload or b"FeatureCollection" in payload or b"interpretacion" in payload
print("OK consulta estadistica")
print("SMOKE TEST OK")
