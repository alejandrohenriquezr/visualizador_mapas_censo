# -*- coding: utf-8 -*-
"""Pruebas de regresión para filtros geográficos por código y números romanos."""
import unittest

from dictionary import VARIABLES, referencia_geografica_por_codigo
from language_normalizer import normalizar_consulta
from nl_parser import interpretar_consulta

ROMANOS = {
    1: "I", 2: "II", 3: "III", 4: "IV", 5: "V", 6: "VI",
    7: "VII", 8: "VIII", 9: "IX", 10: "X", 11: "XI",
    12: "XII", 13: "XIII", 14: "XIV", 15: "XV", 16: "XVI",
}


class CodigosGeograficosTests(unittest.TestCase):
    def assertFiltro(self, pregunta, nivel, codigo):
        r = interpretar_consulta(pregunta)
        self.assertEqual(r["filtro_geografico_nivel"], nivel, (pregunta, r))
        self.assertEqual(str(r["filtro_geografico_codigo"]), str(codigo), (pregunta, r))
        return r

    def test_region_13(self):
        self.assertFiltro("cantidad de personas de la región 13", "region", "13")

    def test_region_xiii(self):
        self.assertFiltro("cantidad de personas de la región XIII", "region", "13")

    def test_xii_region(self):
        self.assertFiltro("cantidad de personas de la XII región", "region", "12")

    def test_comuna_9101(self):
        r = self.assertFiltro("cantidad de hogares de la comuna 9101", "comuna", "9101")
        self.assertEqual(r["nivel_geografico"], "comuna")

    def test_comuna_con_cero_inicial(self):
        self.assertFiltro("cantidad de hogares de la comuna 09101", "comuna", "9101")

    def test_codigo_de_comuna(self):
        self.assertFiltro("cantidad de personas del código de comuna 9101", "comuna", "9101")

    def test_provincia_91(self):
        r = self.assertFiltro("cantidad de viviendas de la provincia 91", "provincia", "91")
        self.assertEqual(r["nivel_geografico"], "provincia")

    def test_categoria_mas_codigo(self):
        r = self.assertFiltro("electricidad por red pública de la provincia 131", "provincia", "131")
        self.assertEqual(r["variable"], "p9_fuente_elect")
        self.assertEqual(r["categoria_valor"], "1")

    def test_distribucion_mas_codigo(self):
        r = self.assertFiltro("tipología de hogar de la comuna 9101", "comuna", "9101")
        self.assertEqual(r["variable"], "tipologia_hogar")
        self.assertEqual(r["operacion"], "distribucion")

    def test_magallanes_no_se_confunde_con_nacionalidad(self):
        r = self.assertFiltro("cantidad de personas de la región XII", "region", "12")
        self.assertEqual(r["variable"], "id_persona")

    def test_codigo_invalido_region(self):
        with self.assertRaisesRegex(ValueError, "No existe una region con código 99"):
            interpretar_consulta("cantidad de personas de la región 99")

    def test_codigo_invalido_provincia(self):
        with self.assertRaisesRegex(ValueError, "No existe una provincia con código 999"):
            interpretar_consulta("cantidad de personas de la provincia 999")

    def test_codigo_invalido_comuna(self):
        with self.assertRaisesRegex(ValueError, "No existe una comuna con código 99999"):
            interpretar_consulta("cantidad de personas de la comuna 99999")

    def test_todas_las_regiones_arabigas_y_romanas(self):
        for codigo in VARIABLES["geografia"]["region"]:
            n = int(codigo)
            for texto in (
                f"región {n}",
                f"región {ROMANOS[n]}",
                f"{ROMANOS[n]} región",
            ):
                ref = referencia_geografica_por_codigo(texto)
                self.assertIsNotNone(ref, texto)
                self.assertEqual(int(ref["codigo"]), n, texto)

    def test_todos_los_codigos_de_provincia(self):
        for codigo in VARIABLES["geografia"]["provincia"]:
            ref = referencia_geografica_por_codigo(f"provincia {codigo}")
            self.assertIsNotNone(ref, codigo)
            self.assertEqual(int(ref["codigo"]), int(codigo))

    def test_todos_los_codigos_de_comuna(self):
        for codigo in VARIABLES["geografia"]["comuna"]:
            ref = referencia_geografica_por_codigo(f"comuna {codigo}")
            self.assertIsNotNone(ref, codigo)
            self.assertEqual(int(ref["codigo"]), int(codigo))

    def test_normalizador_conserva_codigo_como_trazabilidad(self):
        n = normalizar_consulta("personas de la comuna 8104")
        codigo = next(x for x in n["aliases_aplicados"] if x["tipo"] == "codigo_geografico")
        self.assertEqual(codigo["codigo"], "8104")
        self.assertIn("comuna florida", n["texto"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
