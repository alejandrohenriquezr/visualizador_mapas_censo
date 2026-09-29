# -*- coding: utf-8 -*-
"""Aplica al data_engine.py existente las mejoras de rangos, porcentajes y razones.

Uso desde C:\\mapa_censo_interactivo\\backend:
    python aplicar_parche_data_engine.py

El script crea data_engine.py.bak antes de modificar el archivo.
"""
from pathlib import Path
import re
import shutil

RUTA = Path(__file__).resolve().parent / "data_engine.py"
if not RUTA.exists():
    raise SystemExit(f"No se encontró {RUTA}. Copiar este script dentro de la carpeta backend.")

BACKUP = RUTA.with_suffix(".py.bak")
if not BACKUP.exists():
    shutil.copy2(RUTA, BACKUP)

NUEVA_FUNCION = r'''def _construir_sql(intencion: dict, nivel_info: dict, ruta_parquet: Path) -> str:
    """Construye SQL seguro para conteos, porcentajes, rangos y razones verificadas."""
    tabla = intencion["tabla"]
    variable_original = intencion["variable"]
    valor = intencion.get("categoria_valor")
    operacion = intencion.get("operacion", "conteo")
    col_geo = nivel_info["col_parquet"]

    if tabla not in TABLAS_PARQUET or variable_original not in VARIABLES[tabla]["variables"]:
        raise ValueError("Tabla o variable desconocida.")
    if operacion not in ("conteo", "porcentaje", "porcentaje_rango", "promedio",
                         "razon", "razon_tablas"):
        raise ValueError("Operación no admitida.")

    def qid(nombre):
        """Cita identificadores SQL controlados por el diccionario o reglas internas."""
        return '"' + str(nombre).replace('"', '""') + '"'

    def literal(valor_sql):
        """Escapa literales de texto; los identificadores nunca pasan por aquí."""
        return "'" + str(valor_sql).replace("'", "''") + "'"

    def condicion_lista(columna, valores):
        valores = [str(v) for v in (valores or [])]
        if not valores:
            return "FALSE"
        return f"CAST({qid(columna)} AS VARCHAR) IN ({', '.join(literal(v) for v in valores)})"

    def condicion_rango(filtro):
        """Traduce un rango estructurado a comparaciones numéricas explícitas."""
        columna = filtro.get("variable")
        if columna not in VARIABLES[tabla]["variables"]:
            raise ValueError("El filtro numérico usa una variable que no existe en la tabla.")
        expresion = f"TRY_CAST({qid(columna)} AS DOUBLE)"
        condiciones = [f"{expresion} IS NOT NULL"]
        minimo = filtro.get("minimo")
        maximo = filtro.get("maximo")
        dominio_minimo = filtro.get("dominio_minimo")
        dominio_maximo = filtro.get("dominio_maximo")
        if dominio_minimo is not None:
            condiciones.append(f"{expresion} >= {float(dominio_minimo)}")
        if dominio_maximo is not None:
            condiciones.append(f"{expresion} <= {float(dominio_maximo)}")
        if minimo is not None:
            op = ">=" if filtro.get("incluir_minimo", True) else ">"
            condiciones.append(f"{expresion} {op} {float(minimo)}")
        if maximo is not None:
            op = "<=" if filtro.get("incluir_maximo", True) else "<"
            condiciones.append(f"{expresion} {op} {float(maximo)}")
        return " AND ".join(condiciones)

    def filtros_base(tabla_actual):
        """Filtros territoriales y, cuando corresponde, edad mínima."""
        filtros = []
        if intencion.get("edad_minima") is not None:
            edad = intencion.get("variable_edad")
            if tabla_actual != "personas" or edad not in VARIABLES["personas"]["variables"]:
                raise ValueError("Variable de edad no válida.")
            filtros.append(f"TRY_CAST({qid(edad)} AS DOUBLE) >= {int(intencion['edad_minima'])}")
        f_nivel = intencion.get("filtro_geografico_nivel")
        f_codigo = intencion.get("filtro_geografico_codigo")
        if bool(f_nivel) != (f_codigo is not None) or (f_nivel and f_nivel not in NIVELES):
            raise ValueError("Filtro territorial incompleto o no válido.")
        if f_nivel and f_codigo is not None:
            filtros.append(f"{NIVELES[f_nivel]['col_parquet']} = {int(f_codigo)}")
        return filtros

    # Razón entre tablas: usada para tamaño promedio del hogar.
    if operacion == "razon_tablas":
        tabla_num = intencion.get("tabla_numerador")
        tabla_den = intencion.get("tabla_denominador")
        if tabla_num not in TABLAS_PARQUET or tabla_den not in TABLAS_PARQUET:
            raise ValueError("Las tablas de la razón no son válidas.")
        factor = float(intencion.get("factor", 1.0))
        fijos = intencion.get("filtros_fijos_tablas") or {}

        def origen_y_where(tabla_actual):
            ruta = _ruta_parquet(tabla_actual).as_posix().replace("'", "''")
            filtros = filtros_base(tabla_actual)
            for campo, valor_fijo in (fijos.get(tabla_actual) or {}).items():
                # Los filtros internos aceptados están cerrados para evitar identificadores arbitrarios.
                if campo not in {"tipo_operativo"}:
                    raise ValueError(f"Filtro fijo no permitido: {campo}")
                filtros.append(f"{qid(campo)} = {int(valor_fijo)}")
            where = "WHERE " + " AND ".join(filtros) if filtros else ""
            return f"read_parquet('{ruta}')", where

        origen_num, where_num = origen_y_where(tabla_num)
        origen_den, where_den = origen_y_where(tabla_den)
        return f"""
            WITH numerador AS (
                SELECT {col_geo} AS codigo, COUNT(*)::DOUBLE AS n
                FROM {origen_num}
                {where_num}
                GROUP BY {col_geo}
            ), denominador AS (
                SELECT {col_geo} AS codigo, COUNT(*)::DOUBLE AS d
                FROM {origen_den}
                {where_den}
                GROUP BY {col_geo}
            )
            SELECT COALESCE(numerador.codigo, denominador.codigo) AS codigo,
                   {factor} * numerador.n / NULLIF(denominador.d, 0) AS valor
            FROM numerador
            FULL OUTER JOIN denominador USING (codigo)
        """

    variable = qid(variable_original)
    filtros = filtros_base(tabla)
    ruta_sql = ruta_parquet.as_posix().replace("'", "''")
    origen = f"read_parquet('{ruta_sql}')"

    # Los conteos por rango incorporan el rango al WHERE.
    for filtro in intencion.get("filtros_numericos") or []:
        filtros.append(condicion_rango(filtro))

    if operacion == "promedio":
        filtros.append(f"TRY_CAST({variable} AS DOUBLE) IS NOT NULL")
        filtros.append(f"TRY_CAST({variable} AS DOUBLE) >= 0")
        where = "WHERE " + " AND ".join(filtros) if filtros else ""
        return f"""
            SELECT {col_geo} AS codigo, AVG(TRY_CAST({variable} AS DOUBLE)) AS valor
            FROM {origen}
            {where}
            GROUP BY {col_geo}
        """

    if operacion == "porcentaje_rango":
        rango = intencion.get("rango_objetivo")
        if not isinstance(rango, dict):
            raise ValueError("Falta el rango objetivo del porcentaje.")
        # El denominador usa el dominio válido completo de la misma variable.
        denominador = dict(rango)
        denominador["minimo"] = None
        denominador["maximo"] = None
        cond_den = condicion_rango(denominador)
        cond_num = condicion_rango(rango)
        where = "WHERE " + " AND ".join(filtros) if filtros else ""
        return f"""
            SELECT {col_geo} AS codigo,
                   100.0 * SUM(CASE WHEN ({cond_num}) THEN 1 ELSE 0 END)
                   / NULLIF(SUM(CASE WHEN ({cond_den}) THEN 1 ELSE 0 END), 0) AS valor
            FROM {origen}
            {where}
            GROUP BY {col_geo}
        """

    if operacion == "porcentaje":
        if valor is None:
            raise ValueError("El porcentaje requiere una categoría objetivo.")
        cond_num = f"CAST({variable} AS VARCHAR) = {literal(valor)}"
        valores_den = intencion.get("denominador_valores")
        cond_den = condicion_lista(variable_original, valores_den) if valores_den else "TRUE"
        where = "WHERE " + " AND ".join(filtros) if filtros else ""
        return f"""
            SELECT {col_geo} AS codigo,
                   100.0 * SUM(CASE WHEN {cond_num} THEN 1 ELSE 0 END)
                   / NULLIF(SUM(CASE WHEN {cond_den} THEN 1 ELSE 0 END), 0) AS valor
            FROM {origen}
            {where}
            GROUP BY {col_geo}
        """

    if operacion == "razon":
        numerador = condicion_lista(variable_original, intencion.get("numerador_valores"))
        denominador = condicion_lista(variable_original, intencion.get("denominador_valores"))
        factor = float(intencion.get("factor", 1.0))
        where = "WHERE " + " AND ".join(filtros) if filtros else ""
        return f"""
            SELECT {col_geo} AS codigo,
                   {factor} * SUM(CASE WHEN {numerador} THEN 1 ELSE 0 END)
                   / NULLIF(SUM(CASE WHEN {denominador} THEN 1 ELSE 0 END), 0) AS valor
            FROM {origen}
            {where}
            GROUP BY {col_geo}
        """

    # Conteo: COUNT(*) para totales; SUM condicional para categorías concretas.
    agregado = (f"SUM(CASE WHEN CAST({variable} AS VARCHAR) = {literal(valor)} THEN 1 ELSE 0 END)"
                if valor is not None else "COUNT(*)")
    where = "WHERE " + " AND ".join(filtros) if filtros else ""
    return f"""
        SELECT {col_geo} AS codigo, {agregado} AS valor
        FROM {origen}
        {where}
        GROUP BY {col_geo}
    """
'''

texto = RUTA.read_text(encoding="utf-8")
patron = re.compile(r"def _construir_sql\(.*?\n(?=def _firma_geometria\()", re.DOTALL)
if not patron.search(texto):
    raise SystemExit("No se encontró el bloque _construir_sql esperado; no se modificó el archivo.")
texto = patron.sub(NUEVA_FUNCION + "\n\n", texto, count=1)
RUTA.write_text(texto, encoding="utf-8")
print(f"Actualizado: {RUTA}")
print(f"Respaldo:   {BACKUP}")
