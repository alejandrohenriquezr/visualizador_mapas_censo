PARCHE V40 — VISOR MAPAS CENSO
==============================

Objetivo
--------
Este parche implementa de forma general:

1. Botón con icono para expandir el mapa a pantalla completa; en pantalla completa cambia a contraer.
2. Botón con icono para guardar el mapa en PNG.
3. Pantalla completa:
   - mapas de métricas: valor centrado en cada polígono;
   - mapas de tortas: porcentaje y cantidad alrededor de cada torta;
   - indicadores desagregados: valores de las series en el centro territorial.
4. Pantalla normal: panel lateral con el valor/torta/series del ámbito completo consultado (Chile o territorio filtrado).
5. Cruces categóricos: la torta cartográfica usa la PRIMERA variable estadística escrita en la consulta.
   El detalle completo de todas las dimensiones se conserva para Excel y pirámides.
6. Excel: mantiene las dimensiones en el mismo orden en que fueron escritas.
7. Diccionario: agrega personas.edad_grandes_grupos = 0-14 / 15-59 / 60 o más.
8. Edad sin tipo explícito, cuando funciona como dimensión: pregunta por edad simple, quinquenal o grandes grupos.
   Los rangos numéricos (p. ej. 15 a 65 años) siguen usando edad simple sin abrir este diálogo.
9. Tasas, índices, razones y porcentajes registrados: respetan desagregaciones solicitadas (por sexo, edad explícita u otra variable categórica).
   La fórmula del indicador no cambia; se añade GROUP BY por la dimensión solicitada.
10. No ejecuta operaciones Git.

Aplicación
----------
1. Copiar TODO el contenido de esta carpeta a la raíz del proyecto local, por ejemplo:

   C:\mapa_censo_interactivo_github

2. En PowerShell:

   cd C:\mapa_censo_interactivo_github
   python .\APLICAR_PARCHE_V40.py
   python .\VERIFICAR_V40.py

3. Si la verificación queda OK, reconstruir los contenedores que usan backend/frontend:

   docker compose up -d --build backend frontend

   Si docker-compose.yml define nombres/servicios distintos, usar:

   docker compose up -d --build

4. Revisar:

   docker compose ps
   docker compose logs --tail=100 backend
   docker compose logs --tail=100 frontend

Pruebas funcionales recomendadas
---------------------------------
A. "cantidad de personas por región"
   - debe mostrar el panel lateral con el total Chile;
   - pantalla completa debe mostrar el conteo en cada región;
   - Guardar debe producir PNG.

B. "edad quinquenal por sexo por comunas región metropolitana"
   - la torta del mapa debe ser por edad quinquenal;
   - Excel debe mostrar edad quinquenal antes que sexo.

C. "sexo por edad quinquenal por comunas región metropolitana"
   - la torta del mapa debe ser por sexo;
   - Excel debe mostrar sexo antes que edad quinquenal.

D. "distribución de personas por edad por región"
   - debe abrir selector: edad simple / quinquenal / grandes grupos.

E. "distribución de personas por edad en grandes grupos por región"
   - debe usar 0-14, 15-59 y 60 o más.

F. "índice de envejecimiento según sexo por región"
   - debe entregar una serie para Hombre y Mujer en cada región, no ignorar sexo.

G. "tasa de desocupación según sexo por región"
   - debe entregar la tasa separada por sexo usando la misma fórmula de tasa de desocupación.

H. En cualquiera de los mapas anteriores:
   - expandir => mapa a pantalla completa y botón cambia a contraer;
   - contraer => vuelve a la vista original;
   - guardar => PNG.

Respaldo y GitHub
-----------------
APLICAR_PARCHE_V40.py crea una carpeta local _backup_pre_v40_FECHA_HORA antes de modificar archivos.
El parche no ejecuta git commit, git push, git pull, merge, fetch ni ninguna sincronización.
