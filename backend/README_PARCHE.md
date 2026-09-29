# Parche del visor censal — 24-09-2026

## Archivos

- `nl_parser.py`: limpia “Censo 2024”, resuelve conteos totales por entidad y conserva las reglas de rangos.
- `categorical_resolver.py`: incorpora `resolver_conteo_categoria`, que faltaba en la versión disponible.
- `semantic_catalog.py`: incorpora `tamaño promedio del hogar = personas / hogares`.
- `range_resolver.py`: resolvedor de rangos inclusivos/exclusivos ya desarrollado.
- `main.py`: expone en la respuesta las tablas usadas en razones entre tablas.
- `aplicar_parche_data_engine.py`: actualiza el `data_engine.py` existente para ejecutar rangos, porcentajes con denominador válido, índice de masculinidad y razón entre tablas.

## Aplicación en Windows

Desde `C:\mapa_censo_interactivo\backend`:

1. Copiar `nl_parser.py`, `categorical_resolver.py`, `semantic_catalog.py`, `range_resolver.py` y `main.py` sobre los archivos del mismo nombre.
2. Copiar `aplicar_parche_data_engine.py` dentro de `backend`.
3. Ejecutar:

```powershell
python aplicar_parche_data_engine.py
python -m py_compile nl_parser.py categorical_resolver.py semantic_catalog.py range_resolver.py data_engine.py main.py
```

El script crea `data_engine.py.bak` antes de modificar el motor.

## Consultas de verificación

```text
cantidad de población por comuna Censo 2024
cantidad de población de la comuna Santiago
total de personas de la comuna Santiago
total de hogares de la comuna Santiago
viviendas totales de la región Metropolitana de Santiago
viviendas particulares por comuna
viviendas particulares en la comuna de Santiago
porcentaje de personas entre 15 y 65 años por región
cantidad de personas con 8 o menos años de escolaridad por comuna
tamaño promedio del hogar Censo 2024
índice de masculinidad por comuna
```

### Resultado esperado del parser

- `Censo 2024` no participa en la selección semántica.
- Los totales de personas, hogares y viviendas generan `COUNT(*)` de la tabla correspondiente.
- `viviendas particulares` no se absorbe por la regla de totales: debe resolverse como categoría.
- Los rangos generan comparaciones numéricas explícitas y respetan inclusividad.
- Los porcentajes usan el universo válido de la variable cuando el diccionario lo proporciona.
- El tamaño promedio del hogar usa `COUNT(personas) / COUNT(hogares)` por territorio con `tipo_operativo = 2` en ambas tablas.
