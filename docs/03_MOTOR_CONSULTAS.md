# Motor de consultas

La interpretación sigue una estrategia escalonada:

1. normalización lingüística;
2. reglas predefinidas y resolutores especializados;
3. reglas genéricas/QueryPlan;
4. resolución de denominadores para porcentajes/proporciones ambiguas;
5. caché de interpretaciones aprobadas;
6. LLM local como fallback;
7. validación de tabla, variable, categorías y territorio;
8. generación/ejecución DuckDB;
9. presentación y exportación.

El LLM no debe inventar variables, categorías ni fórmulas. Toda interpretación se valida contra los diccionarios antes de ejecutar SQL.
