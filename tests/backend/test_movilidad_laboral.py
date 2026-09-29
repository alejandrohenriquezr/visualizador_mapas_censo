# -*- coding: utf-8 -*-
import sys
import types
import unittest
from pathlib import Path

from nl_parser import interpretar_consulta
from presentation import descripcion_cotidiana


class MovilidadLaboralParserTests(unittest.TestCase):
    def test_salientes_cantidad(self):
        i = interpretar_consulta("personas ocupadas que trabajan fuera de su comuna por comuna")
        self.assertEqual(i["tipo_consulta"], "movilidad_laboral_fase1")
        self.assertEqual(i["movilidad_indicador"], "salientes_cantidad")
        self.assertEqual(i["nivel_geografico"], "comuna")
        self.assertEqual(i["operacion"], "conteo")
        titulo = descripcion_cotidiana(i)
        self.assertTrue(titulo.startswith("Cantidad de personas ocupadas"), titulo)
        self.assertIn("fuera de su comuna de residencia", titulo)

    def test_misma_comuna_cantidad(self):
        i = interpretar_consulta("personas ocupadas que trabajan en su misma comuna por comuna")
        self.assertEqual(i["movilidad_indicador"], "misma_comuna_cantidad")
        self.assertIn("misma comuna de residencia", descripcion_cotidiana(i))

    def test_salientes_porcentaje(self):
        i = interpretar_consulta("porcentaje de ocupados que trabaja fuera de su comuna por comuna")
        self.assertEqual(i["movilidad_indicador"], "salientes_porcentaje")
        self.assertEqual(i["operacion"], "porcentaje")
        self.assertIn("único lugar de trabajo", i["nota_interpretacion"])
        self.assertTrue(descripcion_cotidiana(i).startswith("Porcentaje de personas ocupadas"))

    def test_misma_comuna_porcentaje(self):
        i = interpretar_consulta("porcentaje de ocupados que trabaja en su misma comuna por comuna")
        self.assertEqual(i["movilidad_indicador"], "misma_comuna_porcentaje")
        self.assertEqual(i["operacion"], "porcentaje")

    def test_entrantes_por_comuna_trabajo(self):
        i = interpretar_consulta("personas que llegan desde otra comuna a trabajar por comuna de trabajo")
        self.assertEqual(i["movilidad_indicador"], "entrantes_cantidad")
        self.assertEqual(i["movilidad_geografia"], "trabajo")
        titulo = descripcion_cotidiana(i)
        self.assertIn("llegan desde otra comuna a trabajar", titulo)
        self.assertIn("comunas de trabajo", titulo)

    def test_entrantes_filtro_region_se_refiere_destino(self):
        i = interpretar_consulta(
            "personas que llegan desde otra comuna a trabajar por comuna de la región de la araucanía"
        )
        self.assertEqual(i["movilidad_indicador"], "entrantes_cantidad")
        self.assertEqual(i["filtro_geografico_nivel"], "region")
        self.assertEqual(int(i["filtro_geografico_codigo"]), 9)
        self.assertIn("comunas de trabajo de la región de La Araucanía", descripcion_cotidiana(i))

    def test_consulta_generica_pide_especificar_indicador(self):
        with self.assertRaisesRegex(ValueError, "puede medirse de varias formas"):
            interpretar_consulta("movilidad laboral por comuna")


try:
    import duckdb  # noqa: F401
except ModuleNotFoundError:
    sys.modules["duckdb"] = types.SimpleNamespace(connect=lambda *a, **k: None)

import data_engine  # noqa: E402


class MovilidadLaboralSQLTests(unittest.TestCase):
    def setUp(self):
        self.original = data_engine._ruta_parquet
        data_engine._ruta_parquet = lambda tabla: Path(f"C:/tmp/{tabla}.parquet")

    def tearDown(self):
        data_engine._ruta_parquet = self.original

    def sql(self, pregunta):
        i = interpretar_consulta(pregunta)
        return data_engine._construir_sql_movilidad_laboral_fase1(i)[0]

    def test_sql_salientes(self):
        sql = self.sql("personas ocupadas que trabajan fuera de su comuna por comuna")
        self.assertIn('CAST(p."sit_fuerza_trabajo" AS VARCHAR) = \'1\'', sql)
        self.assertIn('CAST(p."p44_lug_trab" AS VARCHAR) = \'3\'', sql)
        self.assertIn('GROUP BY p."comuna"', sql)
        self.assertIn("COUNT(DISTINCT", sql)

    def test_sql_misma_comuna(self):
        sql = self.sql("personas ocupadas que trabajan en su misma comuna por comuna")
        self.assertIn('CAST(p."p44_lug_trab" AS VARCHAR) IN (\'1\', \'2\')', sql)

    def test_sql_porcentaje_salientes_denominador_valido(self):
        sql = self.sql("porcentaje de ocupados que trabaja fuera de su comuna por comuna")
        self.assertIn("100.0 * COUNT(DISTINCT CASE WHEN", sql)
        self.assertIn('CAST(p."p44_lug_trab" AS VARCHAR) = \'3\'', sql)
        self.assertIn('CAST(p."p44_lug_trab" AS VARCHAR) IN (\'1\', \'2\', \'3\')', sql)
        self.assertNotIn("'4'", sql)
        self.assertNotIn("'5'", sql)

    def test_sql_entrantes_agrupa_por_comuna_trabajo(self):
        sql = self.sql("personas que llegan desde otra comuna a trabajar por comuna de trabajo")
        self.assertIn('TRY_CAST(p."p44_lug_trab_esp" AS BIGINT) AS codigo', sql)
        self.assertIn('CAST(p."p44_lug_trab" AS VARCHAR) = \'3\'', sql)
        self.assertIn('GROUP BY TRY_CAST(p."p44_lug_trab_esp" AS BIGINT)', sql)
        self.assertNotIn('GROUP BY p."comuna"', sql)

    def test_sql_entrantes_region_filtra_region_de_trabajo(self):
        sql = self.sql(
            "personas que llegan desde otra comuna a trabajar por comuna de la región de la araucanía"
        )
        self.assertIn('FLOOR(TRY_CAST(p."p44_lug_trab_esp" AS BIGINT) / 1000)', sql)
        self.assertIn('= 9', sql)
        self.assertNotIn('p."region" = 9', sql)


if __name__ == "__main__":
    unittest.main()


class MovilidadLaboralFase2ParserTests(unittest.TestCase):
    def test_flujo_dirigido_maipu_santiago(self):
        i = interpretar_consulta("personas que viven en Maipú y trabajan en Santiago")
        self.assertEqual(i["tipo_consulta"], "movilidad_laboral_fase2")
        self.assertEqual(i["movilidad_indicador"], "flujo_comunal_cantidad")
        self.assertEqual(int(i["movilidad_origen_codigo"]), 13119)
        self.assertEqual(int(i["movilidad_destino_codigo"]), 13101)
        titulo = descripcion_cotidiana(i)
        self.assertEqual(titulo, "Cantidad de personas ocupadas que viven en Maipú y trabajan en Santiago.")

    def test_flujo_misma_comuna(self):
        i = interpretar_consulta("personas que viven en Temuco y trabajan en Temuco")
        self.assertEqual(int(i["movilidad_origen_codigo"]), 9101)
        self.assertEqual(int(i["movilidad_destino_codigo"]), 9101)

    def test_principales_destinos(self):
        i = interpretar_consulta("principales destinos laborales de quienes viven en Temuco")
        self.assertEqual(i["movilidad_indicador"], "destinos_principales")
        self.assertEqual(int(i["movilidad_origen_codigo"]), 9101)
        self.assertEqual(int(i["movilidad_top_n"]), 10)
        self.assertIn("10 principales comunas de trabajo", descripcion_cotidiana(i))
        self.assertIn("Temuco", descripcion_cotidiana(i))

    def test_top5_destinos(self):
        i = interpretar_consulta("5 principales destinos laborales de las personas que viven en Temuco")
        self.assertEqual(int(i["movilidad_top_n"]), 5)
        self.assertTrue(descripcion_cotidiana(i).startswith("5 principales"))

    def test_principales_origenes(self):
        i = interpretar_consulta("de qué comunas provienen las personas que trabajan en Las Condes")
        self.assertEqual(i["movilidad_indicador"], "origenes_principales")
        self.assertEqual(int(i["movilidad_destino_codigo"]), 13114)
        self.assertIn("comunas de residencia", descripcion_cotidiana(i))
        self.assertIn("Las Condes", descripcion_cotidiana(i))

    def test_solo_otras_comunas_origen(self):
        i = interpretar_consulta("de qué otras comunas provienen las personas que trabajan en Las Condes")
        self.assertTrue(i["movilidad_solo_externos"])

    def test_saldo_comunal(self):
        i = interpretar_consulta("saldo de movilidad laboral por comuna")
        self.assertEqual(i["movilidad_indicador"], "saldo_comunal")
        self.assertEqual(i["operacion"], "suma")
        self.assertIn("entrantes desde otras comunas menos salientes", descripcion_cotidiana(i))

    def test_saldo_region_araucania(self):
        i = interpretar_consulta("saldo de movilidad laboral por comuna de la región de La Araucanía")
        self.assertEqual(i["filtro_geografico_nivel"], "region")
        self.assertEqual(int(i["filtro_geografico_codigo"]), 9)
        self.assertIn("región de La Araucanía", descripcion_cotidiana(i))


class MovilidadLaboralFase2SQLTests(unittest.TestCase):
    def setUp(self):
        self.original = data_engine._ruta_parquet
        data_engine._ruta_parquet = lambda tabla: Path(f"C:/tmp/{tabla}.parquet")

    def tearDown(self):
        data_engine._ruta_parquet = self.original

    def sql(self, pregunta):
        i = interpretar_consulta(pregunta)
        return data_engine._construir_sql_movilidad_laboral_fase2(i)[0]

    def test_sql_flujo_maipu_santiago(self):
        sql = self.sql("personas que viven en Maipú y trabajan en Santiago")
        self.assertIn('p."comuna" = 13119', sql)
        self.assertIn('CAST(p."p44_lug_trab" AS VARCHAR) = \'3\'', sql)
        self.assertIn('TRY_CAST(p."p44_lug_trab_esp" AS BIGINT) = 13101', sql)
        self.assertIn('CAST(p."sit_fuerza_trabajo" AS VARCHAR) = \'1\'', sql)
        self.assertIn("COUNT(DISTINCT", sql)

    def test_sql_flujo_misma_comuna_usa_p44_1_2(self):
        sql = self.sql("personas que viven en Temuco y trabajan en Temuco")
        self.assertIn('p."comuna" = 9101', sql)
        self.assertIn('CAST(p."p44_lug_trab" AS VARCHAR) IN (\'1\', \'2\')', sql)

    def test_sql_destinos_incluye_misma_y_otras_comunas(self):
        sql = self.sql("principales destinos laborales de quienes viven en Temuco")
        self.assertIn('p."comuna" = 9101', sql)
        self.assertIn("CASE WHEN", sql)
        self.assertIn("IN ('1', '2')", sql)
        self.assertIn("= '3'", sql)
        self.assertIn("ORDER BY valor DESC", sql)
        self.assertIn("LIMIT 10", sql)

    def test_sql_origenes_hacia_las_condes(self):
        sql = self.sql("de qué comunas provienen las personas que trabajan en Las Condes")
        self.assertIn('p."comuna" = 13114', sql)
        self.assertIn('TRY_CAST(p."p44_lug_trab_esp" AS BIGINT) = 13114', sql)
        self.assertIn('GROUP BY TRY_CAST(p."comuna" AS BIGINT)', sql)
        self.assertIn("LIMIT 10", sql)

    def test_sql_saldo_construye_entradas_menos_salidas(self):
        sql = self.sql("saldo de movilidad laboral por comuna")
        self.assertIn("WITH flujos AS", sql)
        self.assertIn("SELECT destino AS codigo, 1 AS delta", sql)
        self.assertIn("SELECT origen AS codigo, -1 AS delta", sql)
        self.assertIn("SUM(delta) AS valor", sql)
        self.assertIn('CAST(p."p44_lug_trab" AS VARCHAR) = \'3\'', sql)

    def test_sql_saldo_region_filtra_al_final(self):
        sql = self.sql("saldo de movilidad laboral por comuna de la región de La Araucanía")
        self.assertIn("FROM saldos", sql)
        self.assertIn("FLOOR(codigo / 1000)", sql)
        self.assertIn("= 9", sql)
        self.assertNotIn('p."region" = 9', sql)


class MovilidadLaboralFase3ParserTests(unittest.TestCase):
    def test_matriz_od_basica(self):
        i = interpretar_consulta("matriz de movilidad laboral entre comunas")
        self.assertEqual(i["tipo_consulta"], "movilidad_laboral_fase3")
        self.assertEqual(i["movilidad_indicador"], "matriz_od_comunal")
        self.assertEqual(i["movilidad_metrica"], "cantidad")
        self.assertFalse(i["movilidad_incluir_diagonal"])
        titulo = descripcion_cotidiana(i)
        self.assertTrue(titulo.startswith("Matriz de movilidad laboral"), titulo)
        self.assertIn("comuna de residencia", titulo)
        self.assertIn("comuna de trabajo", titulo)

    def test_matriz_incluye_misma_comuna_solo_si_se_pide(self):
        i = interpretar_consulta("matriz de movilidad laboral entre comunas incluyendo la misma comuna")
        self.assertTrue(i["movilidad_incluir_diagonal"])

    def test_matriz_region_origen_y_destino_chile(self):
        i = interpretar_consulta("matriz de movilidad laboral de las comunas de La Araucanía")
        self.assertEqual(int(i["movilidad_region_origen_codigo"]), 9)
        self.assertIsNone(i.get("movilidad_region_destino_codigo"))
        self.assertIn("residencia en la región de La Araucanía", descripcion_cotidiana(i))

    def test_matriz_entre_comunas_region_restringe_ambos_lados(self):
        i = interpretar_consulta("movilidad laboral entre comunas de La Araucanía")
        self.assertEqual(int(i["movilidad_region_origen_codigo"]), 9)
        self.assertEqual(int(i["movilidad_region_destino_codigo"]), 9)

    def test_matriz_desde_comuna(self):
        i = interpretar_consulta("matriz de movilidad laboral desde Temuco")
        self.assertEqual(int(i["movilidad_origen_codigo"]), 9101)
        self.assertEqual(i["movilidad_origen_nombre"], "Temuco")

    def test_matriz_hacia_comuna(self):
        i = interpretar_consulta("movilidad laboral hacia Las Condes")
        self.assertEqual(int(i["movilidad_destino_codigo"]), 13114)
        self.assertEqual(i["movilidad_destino_nombre"], "Las Condes")

    def test_ranking_top20_excluye_diagonal_por_defecto(self):
        i = interpretar_consulta("20 principales flujos laborales entre comunas")
        self.assertEqual(i["movilidad_indicador"], "ranking_flujos_comunales")
        self.assertEqual(int(i["movilidad_top_n"]), 20)
        self.assertFalse(i["movilidad_incluir_diagonal"])
        self.assertTrue(descripcion_cotidiana(i).startswith("20 principales flujos laborales"))

    def test_matriz_porcentaje_origen(self):
        i = interpretar_consulta("matriz de movilidad laboral porcentaje por comuna de residencia")
        self.assertEqual(i["movilidad_metrica"], "porcentaje_origen")
        self.assertEqual(i["operacion"], "porcentaje")
        self.assertIn("porcentaje por comuna de residencia", descripcion_cotidiana(i).lower())

    def test_matriz_porcentaje_destino(self):
        i = interpretar_consulta("matriz de movilidad laboral porcentaje por comuna de trabajo")
        self.assertEqual(i["movilidad_metrica"], "porcentaje_destino")
        self.assertEqual(i["operacion"], "porcentaje")

    def test_porcentaje_sin_base_pide_aclaracion(self):
        with self.assertRaisesRegex(ValueError, "indica la base"):
            interpretar_consulta("matriz de movilidad laboral en porcentaje entre comunas")

    def test_filtros_sexo_edad_y_transporte(self):
        i = interpretar_consulta(
            "matriz de movilidad laboral de mujeres entre 20 y 39 años en bicicleta"
        )
        filtros = {(f["variable"], f["op"], str(f.get("valor"))) for f in i["movilidad_filtros_persona"] if f["op"] != "between"}
        self.assertIn(("sexo", "=", "2"), filtros)
        self.assertIn(("p45_medio_transporte", "=", "4"), filtros)
        edad = next(f for f in i["movilidad_filtros_persona"] if f["variable"] == "edad")
        self.assertEqual((edad["min"], edad["max"]), (20, 39))
        titulo = descripcion_cotidiana(i)
        self.assertIn("mujeres", titulo)
        self.assertIn("entre 20 y 39 años", titulo)
        self.assertIn("bicicleta", titulo)

    def test_filtro_discapacidad(self):
        i = interpretar_consulta("matriz de movilidad laboral de personas con discapacidad entre comunas")
        self.assertTrue(any(f["variable"] == "discapacidad" and str(f["valor"]) == "1"
                            for f in i["movilidad_filtros_persona"]))

    def test_filtro_actividad_construccion(self):
        i = interpretar_consulta("matriz de movilidad laboral entre comunas de personas que trabajan en construcción")
        self.assertTrue(any(f["variable"] == "cod_caenes" and str(f["valor"]) == "F"
                            for f in i["movilidad_filtros_persona"]))


class MovilidadLaboralFase3SQLTests(unittest.TestCase):
    def setUp(self):
        self.original = data_engine._ruta_parquet
        data_engine._ruta_parquet = lambda tabla: Path(f"C:/tmp/{tabla}.parquet")

    def tearDown(self):
        data_engine._ruta_parquet = self.original

    def sql(self, pregunta):
        i = interpretar_consulta(pregunta)
        return data_engine._construir_sql_movilidad_laboral_fase3(i)[0]

    def test_sql_matriz_construye_origen_destino(self):
        sql = self.sql("matriz de movilidad laboral entre comunas")
        self.assertIn('TRY_CAST(p."comuna" AS BIGINT) AS origen', sql)
        self.assertIn("CASE WHEN", sql)
        self.assertIn('CAST(p."p44_lug_trab" AS VARCHAR) IN (\'1\', \'2\')', sql)
        self.assertIn('CAST(p."p44_lug_trab" AS VARCHAR) = \'3\'', sql)
        self.assertIn("GROUP BY origen, destino", sql)
        self.assertIn("porcentaje_origen", sql)
        self.assertIn("porcentaje_destino", sql)

    def test_sql_matriz_default_excluye_diagonal(self):
        sql = self.sql("matriz de movilidad laboral entre comunas")
        self.assertIn("origen <> destino", sql)

    def test_sql_ranking_excluye_diagonal_y_limita(self):
        sql = self.sql("20 principales flujos laborales entre comunas")
        self.assertIn("origen <> destino", sql)
        self.assertIn("LIMIT 20", sql)

    def test_sql_region_origen_sin_restringir_destino(self):
        sql = self.sql("matriz de movilidad laboral de las comunas de La Araucanía")
        self.assertIn("FLOOR(origen / 1000)", sql)
        self.assertIn("= 9", sql)
        self.assertNotIn("FLOOR(destino / 1000) AS INTEGER) = 9", sql)

    def test_sql_region_ambos_lados(self):
        sql = self.sql("movilidad laboral entre comunas de La Araucanía")
        self.assertIn("FLOOR(origen / 1000)", sql)
        self.assertIn("FLOOR(destino / 1000)", sql)

    def test_sql_desde_temucoy_hacia_las_condes(self):
        sql_o = self.sql("matriz de movilidad laboral desde Temuco")
        self.assertIn("origen = 9101", sql_o)
        sql_d = self.sql("movilidad laboral hacia Las Condes")
        self.assertIn("destino = 13114", sql_d)

    def test_sql_porcentajes_se_calculan_con_ventanas(self):
        sql = self.sql("matriz de movilidad laboral porcentaje por comuna de residencia")
        self.assertIn("SUM(cantidad) OVER (PARTITION BY origen)", sql)
        self.assertIn("SUM(cantidad) OVER (PARTITION BY destino)", sql)

    def test_sql_exclusion_diagonal_antes_del_denominador(self):
        sql = self.sql("matriz de movilidad laboral porcentaje por comuna de residencia sin incluir la misma comuna")
        pos_scope = sql.index("origen <> destino")
        pos_metricas = sql.index("metricas AS")
        self.assertLess(pos_scope, pos_metricas)

    def test_sql_filtros_persona(self):
        sql = self.sql("matriz de movilidad laboral de mujeres entre 20 y 39 años en bicicleta")
        self.assertIn('CAST(p."sexo" AS VARCHAR) = \'2\'', sql)
        self.assertIn('TRY_CAST(p."edad" AS DOUBLE) >= 20', sql)
        self.assertIn('TRY_CAST(p."edad" AS DOUBLE) <= 39', sql)
        self.assertIn('CAST(p."p45_medio_transporte" AS VARCHAR) = \'4\'', sql)

    def test_sql_actividad_construccion(self):
        sql = self.sql("matriz de movilidad laboral entre comunas de personas que trabajan en construcción")
        self.assertIn('CAST(p."cod_caenes" AS VARCHAR) = \'F\'', sql)
