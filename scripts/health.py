import json, urllib.request
from ops_common import base_url
with urllib.request.urlopen(base_url().rstrip("/")+"/api/salud/detallada",timeout=30) as r:
    data=json.loads(r.read().decode("utf-8"))
print(json.dumps(data,ensure_ascii=False,indent=2))
if data.get("estado")!="ok": raise SystemExit(1)
