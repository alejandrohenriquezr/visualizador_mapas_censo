# Indicadores calculados a partir del diccionario censal



El LLM deja de ser la autoridad para los cálculos conocidos. Antes de llamar a
Ollama, `semantic_catalog.py` busca en `diccionario_variables.json` —generado
desde el Excel oficial— la variable y las categorías por su descripción y
etiqueta. Los códigos no están escritos a mano.

Se incorporan estas fórmulas verificadas:

- **Porcentaje de viviendas particulares en venta**: usa la categoría oficial
  `En venta o arriendo` de la variable detallada de estado de ocupación. El
  sistema muestra una nota porque el diccionario no permite separar venta de
  arriendo.
- **Porcentaje de alfabetización**: personas que respondieron `Sí` a
  `¿Sabe leer y escribir?`, dividido por las respuestas válidas `Sí + No`.
  Los menores fuera del universo y los códigos `No aplica`/`No respuesta` no
  entran en el denominador.
- **Índice de masculinidad**: `100 × hombres / mujeres`. También reconoce el
  error frecuente `índice de marculinidad`.

Además, todos los porcentajes de categorías —incluido porcentaje de mujeres—
excluyen automáticamente del denominador códigos negativos, `NA`, `No aplica`,
`No respuesta`, valores suprimidos y etiquetas equivalentes presentes en el
diccionario.

## Seguridad semántica

Si se pide un índice o razón que aún no tiene fórmula registrada, el sistema
devuelve un mensaje claro en lugar de inventar una fórmula o transformarlo en
conteo. Para agregar otro índice se debe registrar en `semantic_catalog.py` su
variable, numerador, denominador, factor y descripción cotidiana.

Ningún LLM puede garantizar el 100 % de las formulaciones libres futuras. Esta
arquitectura sí permite garantizar los indicadores registrados y fallar de
forma explícita para los demás, evitando mapas numéricamente incorrectos.

## Pruebas realizadas

Se probaron ocho casos automatizados en total, entre ellos:

- alfabetización excluyendo `No respuesta` y `No aplica`;
- masculinidad con el texto `marculinidad`;
- viviendas en venta usando la categoría combinada oficial;
- porcentaje de mujeres excluyendo respuestas inválidas;
- la regresión que evita elegir `cantidad de hijas mujeres nacidas`;
- conteos con ceros y las cinco etapas de progreso.

Las pruebas usan parquet sintético y no requieren Ollama ni los microdatos.
