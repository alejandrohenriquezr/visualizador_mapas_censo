# -*- coding: utf-8 -*-
"""Pruebas de regresión de la capa de lenguaje del Visor Censo 2024."""
import unittest

from categorical_resolver import AmbiguedadVariable
from dictionary import buscar_variables
from language_normalizer import normalizar_consulta
from nl_parser import interpretar_consulta


class LenguajeCensoTests(unittest.TestCase):
    def assertIntent(self, pregunta, **esperado):
        resultado = interpretar_consulta(pregunta)
        for clave, valor in esperado.items():
            self.assertEqual(resultado.get(clave), valor, (pregunta, clave, resultado))
        return resultado

    def test_nacimiento_venezuela_rm(self):
        self.assertIntent(
            "personas nacidas en venezuela en región metropolitana",
            tabla="personas", variable="p25_lug_nacimiento_esp",
            categoria_valor="862", operacion="conteo",
            filtro_geografico_nivel="region", filtro_geografico_codigo="13",
        )

    def test_nacimiento_venezuela_con_errores(self):
        r = self.assertIntent(
            "porcentage de persnas nacidaas en venezula en rejion metropoiltana",
            tabla="personas", variable="p25_lug_nacimiento_esp",
            categoria_valor="862", operacion="porcentaje",
            filtro_geografico_nivel="region", filtro_geografico_codigo="13",
        )
        corregidos = {x["original"]: x["corregido"] for x in r["_correcciones_ortograficas"]}
        self.assertEqual(corregidos["venezula"], "venezuela")
        self.assertEqual(corregidos["rejion"], "region")

    def test_nacionalidad_venezolana(self):
        self.assertIntent(
            "personas de nacionalidad venezolana por región",
            tabla="personas", variable="p27_nacionalidad_esp",
            categoria_valor="862", nivel_geografico="region",
        )

    def test_demonimo_ambiguo(self):
        with self.assertRaises(AmbiguedadVariable):
            interpretar_consulta("venezolanos por comuna")

    def test_depa(self):
        self.assertIntent(
            "cantidad de depas por comuna",
            tabla="viviendas", variable="p2_tipo_vivienda",
            categoria_valor="3", nivel_geografico="comuna",
        )

    def test_sin_pega(self):
        self.assertIntent(
            "personas sin pega por comuna",
            tabla="personas", variable="sit_fuerza_trabajo",
            categoria_valor="2", nivel_geografico="comuna",
        )

    def test_a_patita(self):
        self.assertIntent(
            "personas que van a la pega a patita por comuna",
            tabla="personas", variable="p45_medio_transporte",
            categoria_valor="3", nivel_geografico="comuna",
        )

    def test_starlink_si(self):
        self.assertIntent(
            "hogares con starlink por comuna",
            tabla="hogares", variable="p15f_serv_internet_satelital",
            categoria_valor="1", nivel_geografico="comuna",
        )

    def test_starlink_no(self):
        self.assertIntent(
            "hogares sin starlink por comuna",
            tabla="hogares", variable="p15f_serv_internet_satelital",
            categoria_valor="2", nivel_geografico="comuna",
        )

    def test_celu(self):
        self.assertIntent(
            "hogares con celu por comuna",
            tabla="hogares", variable="p15a_serv_tel_movil",
            categoria_valor="1", nivel_geografico="comuna",
        )

    def test_rm(self):
        self.assertIntent(
            "personas nacidas en venezuela en la rm",
            variable="p25_lug_nacimiento_esp", categoria_valor="862",
            filtro_geografico_nivel="region", filtro_geografico_codigo="13",
        )

    def test_quinta_region(self):
        self.assertIntent(
            "personas nacidas en peru en la quinta región",
            variable="p25_lug_nacimiento_esp", categoria_valor="604",
            filtro_geografico_nivel="region", filtro_geografico_codigo="5",
        )

    def test_quilpue_con_error(self):
        self.assertIntent(
            "cantidad de personas en comuna de quilpe",
            tabla="personas", variable="id_persona", operacion="conteo",
            nivel_geografico="comuna", filtro_geografico_nivel="comuna",
            filtro_geografico_codigo="5801",
        )

    def test_viviendas_particulares(self):
        self.assertIntent(
            "viviendas particulares por comuna",
            tabla="viviendas", variable="tipo_operativo",
            categoria_valor="2", nivel_geografico="comuna",
        )

    def test_censo_2024_se_elimina(self):
        n = normalizar_consulta("cantidad de casas en Chile Censo 2024")
        self.assertNotIn("censo 2024", n["texto"])
        self.assertIntent(
            "cantidad de casas en Chile Censo 2024",
            tabla="viviendas", variable="p2_tipo_vivienda",
            categoria_valor="1", nivel_geografico="region",
        )


    def test_nacidos_fuera_de_chile(self):
        self.assertIntent(
            "cantidad de personas nacidas fuera de Chile por región",
            tabla="personas", variable="p25_lug_nacimiento",
            categoria_valor="3", operacion="conteo", nivel_geografico="region",
        )

    def test_rango_edad_no_se_rompe(self):
        r = self.assertIntent(
            "porcentaje de personas entre 15 y 65 años por región",
            tabla="personas", variable="edad", operacion="porcentaje_rango",
            nivel_geografico="region",
        )
        self.assertEqual(r["rango_objetivo"]["minimo"], 15.0)
        self.assertEqual(r["rango_objetivo"]["maximo"], 65.0)

    def test_rango_escolaridad_no_se_rompe(self):
        r = self.assertIntent(
            "cantidad de personas con 8 o menos años de escolaridad por comuna",
            tabla="personas", variable="escolaridad", operacion="conteo",
            nivel_geografico="comuna",
        )
        self.assertEqual(r["filtros_numericos"][0]["maximo"], 8.0)

    def test_nacionalidad_chilena(self):
        self.assertIntent(
            "personas de nacionalidad chilena por región",
            tabla="personas", variable="p27_nacionalidad_rec",
            categoria_valor="1", nivel_geografico="region",
        )

    def test_indigenas(self):
        self.assertIntent(
            "personas indígenas por comuna",
            tabla="personas", variable="p28_autoid_pueblo",
            categoria_valor="1", nivel_geografico="comuna",
        )

    def test_afros(self):
        self.assertIntent(
            "cantidad de afros por región",
            tabla="personas", variable="p29_afrodescendencia",
            categoria_valor="1", nivel_geografico="region",
        )

    def test_geografia_no_compite_como_variable(self):
        candidatos = buscar_variables("personas nacidas en venezuela en region metropolitana", top_n=10)
        variables = {x["variable"] for x in candidatos}
        self.assertNotIn("region", variables)
        self.assertNotIn("comuna", variables)
        self.assertIn("p25_lug_nacimiento_esp", variables)


if __name__ == "__main__":
    unittest.main(verbosity=2)
