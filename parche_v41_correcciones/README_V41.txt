PARCHE V41 — CRUCES, RESUMEN, PIRÁMIDE Y PNG
================================================

Este parche corrige cuatro regresiones observadas después de V40:

1) CRUCES CON TORTAS
   - La torta representa SOLO la primera variable escrita en la consulta.
   - Ejemplo: "sexo según grupo de edad quinquenal por región" -> torta por sexo.
   - Ejemplo: "grupo de edad quinquenal según sexo por región" -> torta por edad quinquenal.
   - Las combinaciones completas se conservan en distribucion_completa para Excel y pirámide.
   - Se reconoce también la forma natural "grupo de edad quinquenal".

2) ÁMBITO CONSULTADO
   - En tortas ya no se dibuja otra torta lateral.
   - Se muestra texto con porcentaje y cantidad, por ejemplo:
     "País: 50,6 % hombres (3.588.582 personas) y 49,4 % mujeres (... personas)."

3) PIRÁMIDE
   - Reconoce rótulos como "30-34" y "85 o más" aunque no lleven la palabra "años".
   - Al activar Pirámide se ocultan mapa, leyenda, resumen y controles cartográficos.
   - Al volver al mapa se recalcula su tamaño y encuadre.

4) FULLSCREEN / PNG
   - Al entrar/salir de pantalla completa se vuelve a encuadrar el territorio consultado.
   - Antes de exportar PNG se ajusta el mapa a los resultados y se espera la carga de mosaicos.
   - La captura usa dimensiones explícitas del área del mapa.

APLICACIÓN (PowerShell)
-----------------------
Desde C:\mapa_censo_interactivo_github:

    python .\APLICAR_PARCHE_V41.py
    python .\VERIFICAR_V41.py
    docker compose up -d --build backend frontend

Luego verifica:

    docker compose ps

PRUEBAS RECOMENDADAS
--------------------
A. ocupados por sexo según grupo de edad quinquenal por región
   Esperado: tortas Hombre/Mujer, no combinaciones sexo×edad.
   El resumen lateral debe ser texto.
   La pirámide debe dibujarse.

B. ocupados por grupo de edad quinquenal según sexo por región
   Esperado: tortas de edad quinquenal, no combinaciones edad×sexo.

C. porcentaje de viviendas con hacinamiento crítico por región
   Entrar a fullscreen y guardar PNG.
   Esperado: Chile encuadrado, sin mapa mundial ni territorio cortado.

IMPORTANTE SOBRE DOCKER
-----------------------
El arreglo manual de red realizado antes con:

    docker network connect --alias cartography visor-censo_visor_net visor-censo-cartography-1

se pierde si el contenedor cartography se recrea. La solución permanente es que el servicio
"cartography" pertenezca a la misma red "visor_net" en docker-compose.yml. Este parche V41
NO modifica docker-compose.yml para no mezclar la corrección funcional con la infraestructura.

GIT / GITHUB
------------
Este parche NO ejecuta git add, commit, pull, push ni sincronización con GitHub.
