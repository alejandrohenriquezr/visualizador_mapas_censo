import json, sys, urllib.request
base=(sys.argv[1] if len(sys.argv)>1 else "http://localhost:8010").rstrip("/")
def get(path, timeout=300):
    with urllib.request.urlopen(base+path, timeout=timeout) as r: return r.status, r.read()
status,body=get("/api/salud",30); assert status==200; print("OK backend /api/salud")
status,body=get("/api/salud/detallada",30); assert status==200
health=json.loads(body); assert health.get("estado")=="ok",health
print("OK salud detallada",",".join(sorted(health.get("componentes",{}).keys())))
status,body=get("/api/geometrias/region",300); assert status==200 and len(body)>1000; print("OK cartografia region",len(body),"bytes")
status,body=get("/",30); assert status==200 and b"html" in body.lower(); print("OK frontend /")
req=urllib.request.Request(base+"/api/consulta/progreso",data=json.dumps({"pregunta":"cantidad de poblacion por region"}).encode(),headers={"Content-Type":"application/json"},method="POST")
with urllib.request.urlopen(req,timeout=300) as r: payload=r.read()
assert b"resultado" in payload or b"FeatureCollection" in payload or b"interpretacion" in payload
print("OK consulta estadistica"); print("SMOKE TEST OK")
