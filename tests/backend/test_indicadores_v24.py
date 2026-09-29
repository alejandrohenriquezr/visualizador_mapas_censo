# -*- coding: utf-8 -*-
import sys
import types
import unittest
from pathlib import Path

from nl_parser import interpretar_consulta
from presentation import descripcion_cotidiana


class MapuzugunV24Tests(unittest.TestCase):
    def test_conteo_mapuzugun_es_categoria_no_distribucion(self):
        i = interpretar_consulta("personas que hablan o entienden Mapuzugún por región")
        self.assertEqual(i["tipo_consulta"], "lengua_indigena_especifica")
        self.assertEqual(i["variable"], "p30_lengua_indigena")
        self.assertEqual(i["categoria_valor"], "1")
        self.assertEqual(i["operacion"], "conteo")
        self.assertNotEqual(i["operacion"], "distribucion")
        self.assertEqual(
            descripcion_cotidiana(i),
            "Cantidad de personas que hablan o entienden Mapuzugún, según regiones.",
        )

    def test_porcentaje_mapuzugun(self):
        i = interpretar_consulta("porcentaje de personas que hablan o entienden Mapuzugún por región")
        self.assertEqual(i["variable"], "p30_lengua_indigena")
        self.assertEqual(i["categoria_valor"], "1")
        self.assertEqual(i["operacion"], "porcentaje")
        self.assertEqual(i["denominador_valores"], ["1","2","3","4","5","6","7","8","9"])
        titulo = descripcion_cotidiana(i)
        self.assertEqual(titulo, "Porcentaje de personas que hablan o entienden Mapuzugún, según regiones.")
        self.assertNotIn("Distribución", titulo)

    def test_mapuzugun_sin_tilde(self):
        i = interpretar_consulta("personas que hablan o entienden mapuzugun por comuna")
        self.assertEqual((i["variable"], i["categoria_valor"]), ("p30_lengua_indigena", "1"))
        self.assertEqual(i["nivel_geografico"], "comuna")


class IndicadoresV24ParserTests(unittest.TestCase):
    CASOS = {
        "índice de envejecimiento por región": "envejecimiento",
        "indice de dependencia laboral por región": "dependencia_total",
        "Dependencia Total (IDD) por región": "dependencia_total",
        "índice de Dependencia Juvenil por región": "dependencia_juvenil",
        "Dependencia de Mayores por región": "dependencia_mayores",
        "tasa de ocupación por región": "tasa_ocupacion",
        "tasa de desocupación por región": "tasa_desocupacion",
    }

    def test_resuelve_indicadores(self):
        for q, indicador in self.CASOS.items():
            with self.subTest(q=q):
                i = interpretar_consulta(q)
                self.assertEqual(i["tipo_consulta"], "indicador_derivado_v24")
                self.assertEqual(i["indicador_id"], indicador)
                self.assertEqual(i["tabla"], "personas")
                self.assertEqual(i["operacion"], "razon")
                titulo = descripcion_cotidiana(i)
                self.assertNotIn("Cantidad de personas", titulo)
                self.assertNotIn("Distribución", titulo)

    def test_leyenda_envejecimiento_explica_denominador(self):
        titulo = descripcion_cotidiana(interpretar_consulta("índice de envejecimiento por región"))
        self.assertIn("65 años o más", titulo)
        self.assertIn("100 personas de 0 a 14 años", titulo)

    def test_leyenda_idd_explica_formula(self):
        titulo = descripcion_cotidiana(interpretar_consulta("Dependencia Total (IDD) por región"))
        self.assertIn("0 a 14 años", titulo)
        self.assertIn("65 años o más", titulo)
        self.assertIn("100 personas de 15 a 64 años", titulo)

    def test_leyenda_tasa_ocupacion(self):
        titulo = descripcion_cotidiana(interpretar_consulta("tasa de ocupación por región"))
        self.assertIn("ocupadas", titulo)
        self.assertIn("15 años o más", titulo)

    def test_leyenda_tasa_desocupacion(self):
        titulo = descripcion_cotidiana(interpretar_consulta("tasa de desocupación por región"))
        self.assertIn("desocupadas", titulo)
        self.assertIn("fuerza de trabajo", titulo)

    def test_filtro_geografico_se_conserva(self):
        i = interpretar_consulta("índice de envejecimiento por comuna de la región de la araucanía")
        self.assertEqual(i["nivel_geografico"], "comuna")
        self.assertEqual(i["filtro_geografico_nivel"], "region")
        self.assertEqual(int(i["filtro_geografico_codigo"]), 9)
        self.assertIn("La Araucanía", descripcion_cotidiana(i))


try:
    import duckdb  # noqa: F401
except ModuleNotFoundError:
    sys.modules["duckdb"] = types.SimpleNamespace(connect=lambda *a, **k: None)
import data_engine  # noqa: E402


class IndicadoresV24SQLTests(unittest.TestCase):
    def sql(self, consulta):
        i = interpretar_consulta(consulta)
        return data_engine._construir_sql_indicador_derivado_v24(
            i, data_engine.NIVELES[i["nivel_geografico"]], Path("C:/tmp/personas.parquet")
        )

    def test_sql_envejecimiento(self):
        sql = self.sql("índice de envejecimiento por región")
        self.assertIn('TRY_CAST("edad" AS DOUBLE) >= 65', sql)
        self.assertIn('TRY_CAST("edad" AS DOUBLE) BETWEEN 0 AND 14', sql)
        self.assertIn('100.0 *', sql)

    def test_sql_dependencia_total(self):
        sql = self.sql("Dependencia Total (IDD) por región")
        self.assertIn('BETWEEN 0 AND 14', sql)
        self.assertIn('>= 65', sql)
        self.assertIn('BETWEEN 15 AND 64', sql)

    def test_sql_dependencia_juvenil(self):
        sql = self.sql("índice de dependencia juvenil por región")
        self.assertIn('BETWEEN 0 AND 14', sql)
        self.assertIn('BETWEEN 15 AND 64', sql)

    def test_sql_dependencia_mayores(self):
        sql = self.sql("dependencia de mayores por región")
        self.assertIn('>= 65', sql)
        self.assertIn('BETWEEN 15 AND 64', sql)

    def test_sql_tasa_ocupacion_denominador_15_mas(self):
        sql = self.sql("tasa de ocupación por región")
        self.assertIn('CAST("sit_fuerza_trabajo" AS VARCHAR) = \'1\'', sql)
        self.assertIn('TRY_CAST("edad" AS DOUBLE) >= 15', sql)
        self.assertNotIn("IN ('1','2') THEN 1 ELSE 0 END)), 0) AS valor", sql)

    def test_sql_tasa_desocupacion_denominador_fuerza_trabajo(self):
        sql = self.sql("tasa de desocupación por región")
        self.assertIn('CAST("sit_fuerza_trabajo" AS VARCHAR) = \'2\'', sql)
        self.assertIn("CAST(\"sit_fuerza_trabajo\" AS VARCHAR) IN ('1','2')", sql)
        self.assertNotIn("= '3'", sql)

    def test_sql_aplica_region_araucania(self):
        sql = self.sql("índice de envejecimiento por comuna de la región de la araucanía")
        self.assertIn("region = 9", sql)
        self.assertIn("GROUP BY comuna", sql)


if __name__ == "__main__":
    unittest.main()
