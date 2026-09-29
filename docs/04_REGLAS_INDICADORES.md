# Reglas, indicadores y denominadores

Los módulos del backend separan reglas especializadas (educación, discapacidad, rangos, migración interna, movilidad laboral e indicadores censales) de reglas genéricas.

Para tasas e índices metodológicamente definidos, el denominador forma parte de la fórmula y no se pregunta al usuario. Para porcentajes genéricos, si el texto no identifica el denominador y existen varias bases plausibles, el sistema solicita aclaración antes de calcular.

Las matrices origen-destino distinguen residencia/origen y destino. En movilidad laboral la permanencia en la misma comuna está excluida por defecto salvo solicitud explícita.

La documentación histórica de indicadores y denominadores, si estaba disponible en el proyecto origen, se copia a `docs/referencia/`.
