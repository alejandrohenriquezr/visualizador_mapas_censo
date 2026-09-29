# -*- coding: utf-8 -*-
import unittest

from categorical_resolver import AmbiguedadVariable
from nl_parser import interpretar_consulta


class TestEducacion(unittest.TestCase):
    def test_asisten_parvularia(self):
        i = interpretar_consulta("personas que asisten a la educación parvularia por comuna")
        self.assertEqual(i["variable"], "asistencia_parv")
        self.assertEqual(i["categoria_valor"], "1")
        self.assertEqual(i["operacion"], "conteo")
        self.assertEqual(i["nivel_geografico"], "comuna")

    def test_asisten_basica(self):
        i = interpretar_consulta("personas que asisten a la educación básica por región")
        self.assertEqual(i["variable"], "asistencia_basica")
        self.assertEqual(i["categoria_valor"], "1")

    def test_asisten_media(self):
        i = interpretar_consulta("personas que asisten a la educación media por región")
        self.assertEqual(i["variable"], "asistencia_media")
        self.assertEqual(i["categoria_valor"], "1")

    def test_asisten_superior(self):
        i = interpretar_consulta("personas que asisten a la educación superior por región")
        self.assertEqual(i["variable"], "asistencia_superior")
        self.assertEqual(i["categoria_valor"], "1")

    def test_porcentaje_superior(self):
        i = interpretar_consulta("porcentaje de personas que asisten a educación superior por comuna")
        self.assertEqual(i["variable"], "asistencia_superior")
        self.assertEqual(i["categoria_valor"], "1")
        self.assertEqual(i["operacion"], "porcentaje")
        self.assertEqual(i["denominador_valores"], ["1", "2"])

    def test_no_asisten_media(self):
        i = interpretar_consulta("personas que no asisten a educación media por comuna")
        self.assertEqual(i["variable"], "asistencia_media")
        self.assertEqual(i["categoria_valor"], "2")

    def test_educacion_formal_general(self):
        i = interpretar_consulta("personas que asisten a la educación formal por región")
        self.assertEqual(i["variable"], "p33_edu_asiste")
        self.assertEqual(i["categoria_valor"], "1")

    def test_etiqueta_variable_media_da_distribucion(self):
        i = interpretar_consulta("asistencia a nivel de educación media por comuna")
        self.assertEqual(i["variable"], "asistencia_media")
        self.assertEqual(i["operacion"], "distribucion")
        self.assertEqual(i["tipo_visualizacion"], "tortas_mapa")

    def test_estudiantes_sin_nivel_pide_seleccion(self):
        with self.assertRaises(AmbiguedadVariable) as ctx:
            interpretar_consulta("personas estudiantes por región")
        variables = [o["variable"] for o in ctx.exception.opciones]
        self.assertEqual(variables, [
            "p33_edu_asiste", "asistencia_parv", "asistencia_basica",
            "asistencia_media", "asistencia_superior",
        ])

    def test_seleccion_estudiantes_media(self):
        i = interpretar_consulta(
            "personas estudiantes por región",
            tabla_seleccionada="personas",
            variable_seleccionada="asistencia_media",
        )
        self.assertEqual(i["variable"], "asistencia_media")
        self.assertEqual(i["categoria_valor"], "1")
        self.assertEqual(i["operacion"], "conteo")

    def test_seleccion_estudiantes_p33(self):
        i = interpretar_consulta(
            "personas estudiantes por región",
            tabla_seleccionada="personas",
            variable_seleccionada="p33_edu_asiste",
        )
        self.assertEqual(i["variable"], "p33_edu_asiste")
        self.assertEqual(i["categoria_valor"], "1")

    def test_estudiantes_de_media_no_pregunta(self):
        i = interpretar_consulta("estudiantes de educación media por comuna")
        self.assertEqual(i["variable"], "asistencia_media")
        self.assertEqual(i["categoria_valor"], "1")

    def test_estudiantes_universidad(self):
        i = interpretar_consulta("estudiantes de universidad por región")
        self.assertEqual(i["variable"], "asistencia_superior")
        self.assertEqual(i["categoria_valor"], "1")

    def test_educacion_especial_no_se_inventa(self):
        with self.assertRaises(ValueError) as ctx:
            interpretar_consulta("personas que asisten a educación especial por región")
        self.assertIn("no contiene una variable específica", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
