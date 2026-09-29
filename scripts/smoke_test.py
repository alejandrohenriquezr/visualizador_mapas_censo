import gzip, json, sys, urllib.request

base=(sys.argv[1] if len(sys.argv)>1 else "http://localhost:8010").rstrip("/")

def get(path, timeout=300, headers=None):
    req=urllib.request.Request(base+path,headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read(), dict(r.headers.items())

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
if headers.get("Content-Encoding","").lower()=="gzip":
    body=gzip.decompress(encoded)
else:
    body=encoded
assert len(body)>1000
raw_header=int(headers.get("X-Geometry-Raw-Bytes",len(body)))
transfer_header=int(headers.get("X-Geometry-Transfer-Bytes",len(encoded)))
assert raw_header==len(body)
assert transfer_header==len(encoded)
print(
    "OK cartografia region",
    f"transfer={len(encoded)} bytes",
    f"raw={len(body)} bytes",
    f"compresion={headers.get('X-Geometry-Compression-Pct','n/a')}%"
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
