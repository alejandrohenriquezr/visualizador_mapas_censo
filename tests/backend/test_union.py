# -*- coding: utf-8 -*-
import unittest

from categorical_resolver import AmbiguedadVariable
from nl_parser import interpretar_consulta
from union_resolver import UNION_COMUNA, UNION_PARENTESCO, UNION_ESTADO_CIVIL


class UnionAmbiguityTests(unittest.TestCase):
    def test_union_siempre_solicita_seleccion(self):
        for pregunta in (
            "personas conviviente por acuerdo de unión civil",
            "personas de la comuna de La Unión",
            "personas unión",
        ):
            with self.subTest(pregunta=pregunta):
                with self.assertRaises(AmbiguedadVariable) as cm:
                    interpretar_consulta(pregunta)
                opciones = cm.exception.opciones
                self.assertEqual(len(opciones), 3)
                self.assertEqual(
                    {o["variable"] for o in opciones},
                    {UNION_COMUNA, UNION_PARENTESCO, UNION_ESTADO_CIVIL},
                )

    def test_seleccionar_comuna_la_union(self):
        i = interpretar_consulta(
            "personas conviviente por acuerdo de unión civil",
            tabla_seleccionada="geografia",
            variable_seleccionada=UNION_COMUNA,
        )
        self.assertEqual(i["tabla"], "personas")
        self.assertEqual(i["variable"], "id_persona")
        self.assertEqual(i["filtro_geografico_nivel"], "comuna")
        self.assertEqual(str(i["filtro_geografico_codigo"]), "14201")
        self.assertNotEqual(i.get("tipo_consulta"), "cruce")

    def test_seleccionar_parentesco_union_civil(self):
        i = interpretar_consulta(
            "personas conviviente por acuerdo de unión civil",
            tabla_seleccionada="personas",
            variable_seleccionada=UNION_PARENTESCO,
        )
        p = i["plan_cruce"]
        self.assertIsNone(i["filtro_geografico_nivel"])
        self.assertIsNone(i["filtro_geografico_codigo"])
        self.assertEqual(len(p["filtros"]), 1)
        self.assertEqual(p["filtros"][0]["variable"], "parentesco")
        self.assertEqual(p["filtros"][0]["valores"], ["3"])

    def test_seleccionar_estado_civil_union_civil(self):
        i = interpretar_consulta(
            "personas conviviente por acuerdo de unión civil",
            tabla_seleccionada="personas",
            variable_seleccionada=UNION_ESTADO_CIVIL,
        )
        p = i["plan_cruce"]
        self.assertIsNone(i["filtro_geografico_nivel"])
        self.assertIsNone(i["filtro_geografico_codigo"])
        self.assertEqual(len(p["filtros"]), 1)
        self.assertEqual(p["filtros"][0]["variable"], "p23_est_civil")
        self.assertEqual(p["filtros"][0]["valores"], ["3"])

    def test_reunion_no_activa_union(self):
        # La palabra "reunión" no contiene el token independiente "unión".
        try:
            interpretar_consulta("personas que asistieron a una reunión por región")
        except AmbiguedadVariable as exc:
            self.fail(f"'reunión' no debe activar la ambigüedad de Unión: {exc}")
        except Exception:
            # Puede no reconocerse la consulta estadística, pero no debe abrir
            # el selector de Unión.
            pass


if __name__ == "__main__":
    unittest.main()
