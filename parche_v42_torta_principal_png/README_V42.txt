PARCHE V42 — TORTA POR VARIABLE PRINCIPAL + PNG LEAFLET
=======================================================

Regla implementada
------------------
En consultas cruzadas que producen tortas, la torta representa EXCLUSIVAMENTE
la primera variable estadística escrita en la consulta.

Ejemplos:
- "edad quinquenal por sexo por comunas región metropolitana"
  => torta: edad quinquenal. Sexo NO aparece en porciones ni leyenda.
- "sexo por edad quinquenal por comunas región metropolitana"
  => torta: sexo. Edad NO aparece en porciones ni leyenda.

El cruce completo se mantiene en distribucion_completa para Excel y pirámide.

Además
------
- main.py ahora transmite torta_primera_dimension, dimension_torta, dimensiones,
  resumen_ambito y entidad_objetivo; antes los descartaba.
- las respuestas aprobadas antiguas con códigos cruzados ("1|30", etc.) se
  invalidan y recalculan automáticamente.
- el PNG ya no ejecuta fitBounds justo antes de capturar.
- el PNG normaliza los marcadores Leaflet usando sus posiciones reales de
  pantalla en el clon de html2canvas, evitando que las tortas se desplacen.

Instalación
-----------
Descomprime este paquete en la raíz del proyecto de forma que exista:
  C:\mapa_censo_interactivo_github\parche_v42_torta_principal_png\

Desde PowerShell:
  cd C:\mapa_censo_interactivo_github
  python .\parche_v42_torta_principal_png\APLICAR_PARCHE_V42.py
  python .\parche_v42_torta_principal_png\VERIFICAR_V42.py
  docker compose up -d --build backend frontend
  docker compose ps

Pruebas recomendadas
--------------------
1) ocupados por sexo según grupo de edad quinquenal por región
   Esperado: tortas Hombre / Mujer solamente.

2) ocupados por grupo de edad quinquenal según sexo por región
   Esperado: tortas de grupos de edad solamente; sexo no aparece en la leyenda.

3) Guardar PNG de cualquiera de las anteriores.
   Esperado: las tortas permanecen centradas sobre sus regiones.

No Git
------
El instalador no ejecuta git add/commit/push/pull ni modifica GitHub.
