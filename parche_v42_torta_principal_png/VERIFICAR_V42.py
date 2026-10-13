# -*- coding: utf-8 -*-
from pathlib import Path
import py_compile, sys
ROOT=Path.cwd()
checks=[
 (ROOT/'backend'/'main.py','V42: invalida respuestas aprobadas','invalida caché cruzada antigua'),
 (ROOT/'backend'/'main.py','"torta_primera_dimension": resultado.get','main expone marca de variable principal'),
 (ROOT/'backend'/'main.py','"dimension_torta": resultado.get','main expone dimensión de torta'),
 (ROOT/'frontend'/'index.html','/v42-fixes.js','JS V42 enlazado'),
 (ROOT/'frontend'/'index.html','/v42-fixes.css','CSS V42 enlazado'),
 (ROOT/'frontend'/'v42-fixes.js','reagruparPrimeraDimensionV42','reagrupación cliente por primera variable'),
 (ROOT/'frontend'/'v42-fixes.js','normalizarMarcadoresClonV42','normalización de marcadores PNG'),
 (ROOT/'frontend'/'v42-fixes.js','V42 NO ejecuta fitBounds','PNG no reencuadra durante captura'),
]
fallos=[]
for p,n,l in checks:
    if not p.exists() or n not in p.read_text(encoding='utf-8'):
        fallos.append(f'{l}: {p}')
    else: print('OK ',l)
try:
    py_compile.compile(str(ROOT/'backend'/'main.py'),doraise=True)
    print('OK  sintaxis backend/main.py')
except Exception as e: fallos.append('sintaxis main.py: '+str(e))
if fallos:
    print('\nVERIFICACIÓN V42 CON ERRORES:')
    for f in fallos: print(' -',f)
    sys.exit(1)
print('\nVERIFICACIÓN V42: OK')
print('No se ejecutó ninguna operación Git/GitHub.')
