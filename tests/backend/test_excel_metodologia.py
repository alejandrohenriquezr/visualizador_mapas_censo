# -*- coding: utf-8 -*-
import unittest

from methodology import construir_formula, construir_universo


class TestMetodologiaExcel(unittest.TestCase):
    def test_cruce_personas_departamento_sin_internet(self):
        interp = {
            "nivel_geografico": "region",
            "operacion": "conteo",
            "plan_cruce": {
                "entidad_objetivo": "personas",
                "filtros": [
                    {"tabla":"hogares","variable":"p15d_serv_internet_fija","tipo":"categoria","valores":["2"],"etiqueta":"Sin internet fija"},
                    {"tabla":"hogares","variable":"p15e_serv_internet_movil","tipo":"categoria","valores":["2"]},
                    {"tabla":"hogares","variable":"p15f_serv_internet_satelital","tipo":"categoria","valores":["2"]},
                    {"tabla":"viviendas","variable":"p2_tipo_vivienda","tipo":"categoria","valores":["3"]},
                    {"tabla":"personas","variable":"edad","tipo":"rango","minimo":60,"maximo":None,"incluir_minimo":True},
                ],
                "medida":{"operacion":"conteo_distinto","entidad":"personas"},
            },
        }
        u = construir_universo(interp)
        f = construir_formula(interp)
        self.assertIn("internet fija? = No", u)
        self.assertIn("internet móvil desde un celular, tablet o BAM? = No", u)
        self.assertIn("internet por conexión satelital? = No", u)
        self.assertIn("Tipo de vivienda particular = Departamento", u)
        self.assertIn(">= 60", u)
        self.assertIn("-66 (Valor suprimido por anonimización)", u)
        self.assertIn("conteo distinto de personas", f)
        self.assertIn(" Y ", f)

    def test_promedio_escolaridad_rm(self):
        interp = {
            "nivel_geografico":"comuna",
            "filtro_geografico_nivel":"region",
            "filtro_geografico_codigo":"13",
            "operacion":"promedio",
            "plan_cruce":{
                "entidad_objetivo":"personas",
                "universo_ast":{"op":"and","args":[
                    {"tipo":"rango","tabla":"personas","variable":"escolaridad","minimo":0,"maximo":40,"incluir_minimo":True,"incluir_maximo":True},
                    {"tipo":"comparacion","tabla":"personas","variable":"escolaridad","operador":"!=","valor":-99.0},
                ]},
                "medida":{"operacion":"promedio","tabla":"personas","variable":"escolaridad","entidad":"personas"},
            },
        }
        u = construir_universo(interp)
        f = construir_formula(interp)
        self.assertIn("Años de escolaridad", u)
        self.assertIn("-99 (No respuesta)", u)
        self.assertIn("Metropolitana de Santiago", u)
        self.assertIn("suma de los valores válidos", f)
        self.assertIn("cada comuna", f)

    def test_fecundidad_p46(self):
        interp={"tabla":"personas","variable":"p46a_tot_hijs_nac","operacion":"promedio","nivel_geografico":"region"}
        u=construir_universo(interp)
        self.assertIn("Mujeres de 15 años o más", u)
        self.assertIn("-99 (No respuesta)", u)
        self.assertIn("NA (No aplica)", u)

    def test_fecundidad_p47(self):
        interp={"tabla":"personas","variable":"p47a_tot_hijs_sobrev","operacion":"promedio","nivel_geografico":"region"}
        u=construir_universo(interp)
        self.assertIn("al menos una hija o hijo nacido vivo", u)

    def test_lengua_y_religion(self):
        self.assertIn("5 años o más", construir_universo({"tabla":"personas","variable":"p30_lengua_indigena"}))
        self.assertIn("15 años o más", construir_universo({"tabla":"personas","variable":"p31_religion"}))


if __name__ == "__main__":
    unittest.main()
