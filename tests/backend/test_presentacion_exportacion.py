# -*- coding: utf-8 -*-
import unittest

from nl_parser import interpretar_consulta
from presentation import descripcion_cotidiana
from excel_export import _registros_resultado, _exclusiones_calculo


class PresentacionNaturalTests(unittest.TestCase):
    def test_edad_y_dificultad_se_aplican_juntas(self):
        q = ("personas mayores de 65 años con mucha dificultad visual "
             "por comuna de la región de la araucanía")
        i = interpretar_consulta(q)
        self.assertEqual(i.get("tipo_consulta"), "cruce")
        filtros = i["plan_cruce"]["filtros"]
        self.assertTrue(any(f.get("variable") == "edad" and f.get("minimo") == 65
                            and not f.get("incluir_minimo", True) for f in filtros))
        self.assertTrue(any(f.get("variable") == "p32a_dificultad_ver"
                            and f.get("valores") == ["3"] for f in filtros))
        titulo = descripcion_cotidiana(i)
        self.assertEqual(
            titulo,
            "Personas mayores de 65 años con mucha dificultad para ver aun usando "
            "anteojos o lentes, según comunas de la región de La Araucanía."
        )

    def test_titulo_parentesco_natural(self):
        from union_resolver import UNION_PARENTESCO
        i = interpretar_consulta(
            "personas conviviente por acuerdo de unión civil",
            variable_seleccionada=UNION_PARENTESCO,
        )
        titulo = descripcion_cotidiana(i)
        self.assertIn("Cantidad de personas cuyo parentesco con la jefa o jefe de hogar es", titulo)
        self.assertNotIn("filtros:", titulo.lower())
        self.assertNotIn("unidad de conteo", titulo.lower())


class ExportacionEstructuraTests(unittest.TestCase):
    def _respuesta_comuna(self):
        return {
            "tipo_visualizacion": "mapa",
            "nivel_geografico": "comuna",
            "interpretacion": {
                "tabla": "personas", "variable": "p32a_dificultad_ver",
                "operacion": "conteo", "nivel_geografico": "comuna",
                "filtro_geografico_nivel": "region", "filtro_geografico_codigo": 9,
                "plan_cruce": {
                    "entidad_objetivo": "personas", "dimensiones": [],
                    "filtros": [
                        {"tabla": "personas", "variable": "p32a_dificultad_ver",
                         "tipo": "categoria", "valores": ["3"]},
                        {"tabla": "personas", "variable": "edad", "tipo": "rango",
                         "minimo": 65, "maximo": None, "incluir_minimo": False},
                    ],
                },
            },
            "datos": [{"codigo": 9101, "nombre": "Temuco", "valor": 123}],
        }

    def test_region_primaria_y_comuna_secundaria(self):
        filas, resultados = _registros_resultado(self._respuesta_comuna())
        self.assertEqual(resultados, ["Cantidad"])
        fila = filas[0]
        self.assertEqual(fila["Nivel geográfico primario"], "Región")
        self.assertEqual(fila["Nombre del territorio primario"], "La Araucanía")
        self.assertEqual(fila["Nivel geográfico secundario (opcional)"], "Comuna")
        self.assertEqual(fila["Nombre del territorio secundario"], "Temuco")
        self.assertIn("Sí, mucha dificultad", fila["Categoría"])
        self.assertEqual(fila["Cantidad"], 123)

    def test_region_sin_secundario(self):
        r = {
            "tipo_visualizacion": "mapa", "nivel_geografico": "region",
            "interpretacion": {"tabla": "personas", "variable": "edad",
                               "operacion": "conteo", "nivel_geografico": "region"},
            "datos": [{"codigo": 13, "nombre": "Metropolitana de Santiago", "valor": 10}],
        }
        filas, resultados = _registros_resultado(r)
        self.assertEqual(resultados, ["Cantidad"])
        self.assertNotIn("Nivel geográfico secundario (opcional)", filas[0])
        self.assertNotIn("Categoría", filas[0])
        self.assertEqual(filas[0]["Nombre del territorio primario"], "Metropolitana de Santiago")

    def test_exclusiones_diccionario(self):
        exclusiones = _exclusiones_calculo(self._respuesta_comuna()["interpretacion"])
        texto = "\n".join(exclusiones)
        self.assertIn("-99: No respuesta", texto)
        self.assertIn("NA: No aplica", texto)
        self.assertIn("-66: Valor suprimido por anonimización", texto)


if __name__ == "__main__":
    unittest.main()

try:
    import data_engine
except ModuleNotFoundError:
    data_engine = None


@unittest.skipIf(data_engine is None, "DuckDB no está instalado en este entorno")
class PresentacionSQLTests(unittest.TestCase):
    def test_sql_edad_y_dificultad_incluye_ambos_filtros(self):
        from pathlib import Path
        original = data_engine._ruta_parquet
        data_engine._ruta_parquet = lambda tabla: Path(f"C:/tmp/{tabla}.parquet")
        try:
            i = interpretar_consulta(
                "personas mayores de 65 años con mucha dificultad visual "
                "por comuna de la región de la araucanía"
            )
            sql, _ = data_engine._construir_sql_cruce(i)
        finally:
            data_engine._ruta_parquet = original
        self.assertIn('TRY_CAST(p."edad" AS DOUBLE) > 65', sql)
        self.assertIn('CAST(p."p32a_dificultad_ver" AS VARCHAR) IN (\'3\')', sql)
        self.assertIn('p."region" = 9', sql)
