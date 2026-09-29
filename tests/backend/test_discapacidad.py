# -*- coding: utf-8 -*-
"""Pruebas de regresión para discapacidad general y dimensiones P32."""
import tempfile
import unittest
from pathlib import Path

try:
    import duckdb
    import data_engine
except ModuleNotFoundError:
    duckdb = None
    data_engine = None

from categorical_resolver import AmbiguedadVariable
from disability_resolver import DIMENSIONES_P32
from nl_parser import interpretar_consulta


class DiscapacidadParserTests(unittest.TestCase):
    def assertIntent(self, pregunta, **esperado):
        r = interpretar_consulta(pregunta)
        for clave, valor in esperado.items():
            self.assertEqual(r.get(clave), valor, (pregunta, clave, r))
        return r

    def test_con_discapacidad_general(self):
        self.assertIntent(
            "personas con discapacidad por comuna",
            tabla="personas", variable="discapacidad", categoria_valor="1",
            operacion="conteo", nivel_geografico="comuna",
        )

    def test_sin_discapacidad_general(self):
        self.assertIntent(
            "personas sin discapacidad",
            tabla="personas", variable="discapacidad", categoria_valor="2",
            operacion="conteo",
        )

    def test_porcentaje_discapacidad_general_con_region(self):
        self.assertIntent(
            "porcentaje de personas con discapacidad de la región 13",
            tabla="personas", variable="discapacidad", categoria_valor="1",
            operacion="porcentaje", filtro_geografico_nivel="region",
            filtro_geografico_codigo="13",
        )

    def test_discapacidad_sola_es_distribucion_general(self):
        self.assertIntent(
            "discapacidad por región",
            tabla="personas", variable="discapacidad", categoria_valor=None,
            operacion="distribucion", tipo_visualizacion="tortas_mapa",
        )

    def test_dimension_visual_sin_grado(self):
        self.assertIntent(
            "dificultad para ver",
            tabla="personas", variable="p32a_dificultad_ver",
            operacion="distribucion", tipo_visualizacion="tortas_mapa",
        )


    def test_con_dificultad_visual_equivale_mayor_que_uno(self):
        r = self.assertIntent(
            "personas con dificultad para ver por comuna",
            tabla="personas", variable="p32a_dificultad_ver",
            categoria_valor=None, operacion="conteo", nivel_geografico="comuna",
        )
        self.assertEqual(r.get("categoria_valores"), ["2", "3", "4"])

    def test_porcentaje_con_dificultad_usa_2_3_4_sobre_1_4(self):
        r = self.assertIntent(
            "porcentaje de personas con dificultad para oír por región",
            tabla="personas", variable="p32b_dificultad_oir",
            categoria_valor=None, operacion="porcentaje", nivel_geografico="region",
        )
        self.assertEqual(r.get("categoria_valores"), ["2", "3", "4"])
        self.assertEqual(r.get("denominador_valores"), ["1", "2", "3", "4"])

    def test_dificultad_sin_conserva_distribucion_cuatro_grados(self):
        self.assertIntent(
            "dificultad para ver por región",
            variable="p32a_dificultad_ver", operacion="distribucion",
            tipo_visualizacion="tortas_mapa",
        )

    def test_dimension_visual_con_grado(self):
        self.assertIntent(
            "personas con mucha dificultad para ver",
            tabla="personas", variable="p32a_dificultad_ver",
            categoria_valor="3", operacion="conteo",
        )

    def test_no_puede_caminar_es_categoria_4(self):
        self.assertIntent(
            "personas que no pueden caminar",
            tabla="personas", variable="p32c_dificultad_mover",
            categoria_valor="4", operacion="conteo",
        )

    def test_dimension_auditiva_algo(self):
        self.assertIntent(
            "algo de dificultad para escuchar",
            tabla="personas", variable="p32b_dificultad_oir",
            categoria_valor="2", operacion="conteo",
        )

    def test_dimension_cognitiva(self):
        self.assertIntent(
            "problemas para recordar o concentrarse",
            tabla="personas", variable="p32d_dificultad_cogni",
            operacion="distribucion",
        )

    def test_dimension_cuidado(self):
        self.assertIntent(
            "problemas para bañarse o vestirse",
            tabla="personas", variable="p32e_dificultad_cuidado",
            operacion="distribucion",
        )

    def test_dimension_comunicacion(self):
        self.assertIntent(
            "problemas para comunicarse",
            tabla="personas", variable="p32f_dificultad_comunic",
            operacion="distribucion",
        )

    def test_discapacidad_visual_apunta_a_p32_no_derivada(self):
        self.assertIntent(
            "discapacidad visual",
            tabla="personas", variable="p32a_dificultad_ver",
            operacion="distribucion",
        )

    def test_tipo_discapacidad_sin_grado_pide_seleccion(self):
        with self.assertRaises(AmbiguedadVariable) as ctx:
            interpretar_consulta("distribución de personas según tipo de discapacidad")
        self.assertEqual(len(ctx.exception.opciones), 4)
        self.assertTrue(all(o["variable"].startswith("__p32_severidad_")
                            for o in ctx.exception.opciones))

    def test_tipo_discapacidad_seleccion_usuario(self):
        r = interpretar_consulta(
            "distribución de personas según tipo de discapacidad",
            tabla_seleccionada="personas",
            variable_seleccionada="__p32_severidad_3",
        )
        self.assertEqual(r["tipo_consulta"], "dimensiones_funcionales")
        self.assertEqual(r["tipo_visualizacion"], "barras_mapa")
        self.assertEqual(r["categoria_valor"], "3")
        self.assertEqual(r["metrica_dimensiones"], "conteo")
        self.assertEqual(len(r["variables_dimensiones"]), 6)

    def test_tipo_discapacidad_grado_explicito(self):
        r = self.assertIntent(
            "distribución de personas con mucha dificultad según tipo de discapacidad",
            tabla="personas", categoria_valor="3", tipo_consulta="dimensiones_funcionales",
            tipo_visualizacion="barras_mapa", metrica_dimensiones="conteo",
        )
        self.assertEqual(tuple(r["variables_dimensiones"]), tuple(v for v, _ in DIMENSIONES_P32))

    def test_tipo_discapacidad_porcentaje(self):
        self.assertIntent(
            "porcentaje de personas que no pueden hacerlo por tipo de discapacidad",
            tabla="personas", categoria_valor="4", operacion="porcentaje",
            tipo_consulta="dimensiones_funcionales", tipo_visualizacion="barras_mapa",
            metrica_dimensiones="porcentaje",
        )

    def test_tipo_discapacidad_con_comuna(self):
        self.assertIntent(
            "personas con mucha dificultad según tipo de discapacidad de la comuna 9101",
            categoria_valor="3", tipo_consulta="dimensiones_funcionales",
            filtro_geografico_nivel="comuna", filtro_geografico_codigo="9101",
        )

    def test_ciego_no_implica_grado_4(self):
        self.assertIntent(
            "personas ciegas",
            variable="p32a_dificultad_ver", categoria_valor=None,
            operacion="distribucion",
        )

    def test_sordo_no_implica_grado_4(self):
        self.assertIntent(
            "personas sordas",
            variable="p32b_dificultad_oir", categoria_valor=None,
            operacion="distribucion",
        )

    def test_discapacidad_severa_no_se_inventa(self):
        with self.assertRaisesRegex(ValueError, "no distingue grados"):
            interpretar_consulta("personas con discapacidad severa")


@unittest.skipUnless(duckdb is not None and data_engine is not None, "DuckDB no está instalado en este entorno")
class DiscapacidadMotorTests(unittest.TestCase):
    def test_con_dificultad_genera_condicion_in_2_3_4(self):
        intencion = interpretar_consulta("personas con dificultad para ver por región")
        sql = data_engine._construir_sql(
            intencion, data_engine.NIVELES["region"], Path("personas_censo2024.parquet")
        )
        compacto = " ".join(sql.split())
        self.assertIn("IN ('2', '3', '4')", compacto)

    def test_porcentaje_con_dificultad_numera_2_3_4_y_denominador_1_4(self):
        intencion = interpretar_consulta("porcentaje de personas con dificultad para ver por región")
        sql = data_engine._construir_sql(
            intencion, data_engine.NIVELES["region"], Path("personas_censo2024.parquet")
        )
        compacto = " ".join(sql.split())
        self.assertIn("IN ('2', '3', '4')", compacto)
        self.assertIn("IN ('1', '2', '3', '4')", compacto)

    def test_barras_p32_cuentan_y_calculan_porcentaje(self):
        columnas = [v for v, _ in DIMENSIONES_P32]
        filas = [
            # region, comuna, seis P32. Una misma persona puede estar en varias barras.
            (13, 13101, 3, 1, 3, 2, 3, 4),
            (13, 13101, 3, 3, 1, 3, 2, 1),
            (13, 13102, 1, 1, 1, 1, 1, 1),
            (5,  5101,  3, 3, 3, 3, 3, 3),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            parquet = tmp / "personas_censo2024.parquet"
            definicion = ", ".join(["region INTEGER", "provincia INTEGER", "comuna INTEGER"] +
                                   [f'"{c}" INTEGER' for c in columnas])
            con = duckdb.connect(database=":memory:")
            con.execute(f"CREATE TABLE personas ({definicion})")
            placeholders = ",".join(["?"] * (3 + len(columnas)))
            # provincia ficticia 131 para RM y 51 para Valparaíso.
            filas_sql = [(r, 131 if r == 13 else 51, c, *vals) for r, c, *vals in filas]
            con.executemany(f"INSERT INTO personas VALUES ({placeholders})", filas_sql)
            con.execute(f"COPY personas TO '{parquet.as_posix()}' (FORMAT PARQUET)")
            con.close()

            anterior = data_engine.DATOS_DIR
            data_engine.DATOS_DIR = tmp
            data_engine._consultar_sql.cache_clear()
            try:
                intencion = interpretar_consulta(
                    "porcentaje de personas con mucha dificultad por tipo de discapacidad por comuna de la región 13"
                )
                resultado = data_engine.ejecutar_consulta(intencion)
            finally:
                data_engine.DATOS_DIR = anterior
                data_engine._consultar_sql.cache_clear()

        self.assertEqual(resultado["tipo_visualizacion"], "barras_mapa")
        self.assertEqual(len(resultado["datos"]), 2)
        por_codigo = {int(x["codigo"]): x for x in resultado["datos"]}
        por_variable = {x["variable"]: x for x in por_codigo[13101]["barras"]}
        # En comuna 13101 hay 2 respuestas válidas; visual tiene 2 casos de grado 3.
        self.assertEqual(por_variable["p32a_dificultad_ver"]["conteo"], 2)
        self.assertAlmostEqual(por_variable["p32a_dificultad_ver"]["porcentaje"], 100.0)
        # Oír tiene un solo caso de grado 3 en la comuna 13101.
        self.assertEqual(por_variable["p32b_dificultad_oir"]["conteo"], 1)
        self.assertAlmostEqual(por_variable["p32b_dificultad_oir"]["porcentaje"], 50.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
