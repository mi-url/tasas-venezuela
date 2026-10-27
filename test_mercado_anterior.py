"""Las pruebas del mercado de antes del registrador: el archivo publicado y cada lector de fuente.

**El archivo** (`historico/mercado-anterior.jsonl`) se prueba tal como está publicado:
que cada línea esté entera, que siga las reglas de `compilar_mercado_anterior.py` y
que no traiga un salto que la app tomaría por un error. **Los lectores**, con trozos
pequeños escritos aquí con la forma de cada fuente, porque las fuentes no se publican
en este repositorio: cada una sigue en su sitio, citada en el README.

Se corren a mano, al cambiar la recopilación: el archivo está congelado, y el
registrador de cada media hora no depende de él.

Ninguna prueba sale a internet.
"""

import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import compilar_mercado_anterior as m

LINEAS = [json.loads(t) for t in m.SALIDA.read_text(encoding="utf-8").splitlines()]
POR_FECHA = {l["fecha"]: l for l in LINEAS}
FUENTES = {m.XJP, m.WIKIPEDIA, m.CRIPTODOLAR, m.YADIO}


def orden_del_dia(dia: date) -> list[str]:
    return next(o for desde, o in reversed(m.TRAMOS) if dia >= desde)


class ElArchivo(unittest.TestCase):
    def test_una_linea_por_dia_en_orden_y_dentro_del_rango(self):
        fechas = [l["fecha"] for l in LINEAS]
        self.assertEqual(fechas, sorted(set(fechas)))
        self.assertGreaterEqual(fechas[0], m.DESDE.isoformat())
        self.assertLessEqual(fechas[-1], m.HASTA.isoformat())

    def test_llega_hasta_el_dia_antes_del_registrador_y_no_lo_pisa(self):
        # La primera pasada del registrador fue el 2026-07-31 a las 14:13 UTC.
        self.assertEqual(LINEAS[-1]["fecha"], "2026-07-30")
        self.assertEqual(LINEAS[0]["fecha"], "2020-03-30")

    def test_cada_linea_esta_entera_y_ninguna_cifra_es_un_numero(self):
        for l in LINEAS:
            with self.subTest(l["fecha"]):
                self.assertIn(l["fuente"], FUENTES)
                self.assertIsInstance(l["ves_por_usd"], str)
                self.assertGreater(Decimal(l["ves_por_usd"]), 0)
                self.assertIsNotNone(datetime.fromisoformat(l["obtenido"]).utcoffset())
                for fuente, cifra in (l.get("testigos") or {}).items():
                    self.assertIn(fuente, FUENTES - {l["fuente"]})
                    self.assertIsInstance(cifra, str)
                    self.assertGreater(Decimal(cifra), 0)

    def test_la_fuente_es_la_primera_de_su_tramo_que_tiene_el_dia(self):
        for l in LINEAS:
            with self.subTest(l["fecha"]):
                orden = orden_del_dia(date.fromisoformat(l["fecha"]))
                self.assertIn(l["fuente"], orden)
                antes = orden[: orden.index(l["fuente"])]
                self.assertFalse(set(antes) & set(l.get("testigos") or {}), "una fuente que manda más tenía el día")

    def test_los_fines_de_semana_del_paralelo_quedan_sin_cifra(self):
        fin = m.TRAMOS[1][0]
        for l in LINEAS:
            dia = date.fromisoformat(l["fecha"])
            if dia < fin:
                self.assertLess(dia.weekday(), 5, l["fecha"])

    def test_lo_de_soberanos_es_su_cifra_original_entre_un_millon_exacta(self):
        soberanos = [l for l in LINEAS if "cifra_original" in l]
        self.assertGreater(len(soberanos), 1000)
        for l in soberanos:
            with self.subTest(l["fecha"]):
                self.assertEqual(l["escala_original"], "bolívar soberano")
                self.assertEqual(Decimal(l["cifra_original"]).scaleb(-6), Decimal(l["ves_por_usd"]))
                if l["fuente"] == m.WIKIPEDIA:
                    self.assertLess(l["fecha"], m.RECONVERSION.isoformat())

    def test_wikipedia_despues_de_la_reconversion_ya_viene_en_bolivares_de_hoy(self):
        self.assertEqual(POR_FECHA["2021-10-04"], {
            "fecha": "2021-10-04", "ves_por_usd": "4.19", "fuente": m.WIKIPEDIA, "obtenido": "2026-10-27T15:10:01+00:00",
        })

    def test_las_erratas_no_estan_ni_como_testigo(self):
        for fuente, dia in m.ERRATAS | m.ERRATAS_A_MANO:
            with self.subTest((fuente, dia)):
                l = POR_FECHA.get(dia)
                if l is not None:
                    self.assertNotEqual(l["fuente"], fuente)
                    self.assertNotIn(fuente, l.get("testigos") or {})

    def test_la_errata_de_xjp_de_diciembre_de_2020_deja_el_dia_a_wikipedia(self):
        l = POR_FECHA["2020-12-15"]
        self.assertEqual((l["fuente"], l["ves_por_usd"]), (m.WIKIPEDIA, "1.05055435"))
        self.assertNotIn(m.XJP, l.get("testigos") or {})

    def test_los_dos_fines_de_mes_que_el_lector_viejo_perdia(self):
        # Con un mes sin día 31 a la izquierda, en una celda de tres columnas.
        self.assertEqual((POR_FECHA["2022-10-31"]["fuente"], POR_FECHA["2022-10-31"]["ves_por_usd"]), (m.WIKIPEDIA, "9.04"))
        self.assertEqual((POR_FECHA["2024-12-31"]["fuente"], POR_FECHA["2024-12-31"]["ves_por_usd"]), (m.WIKIPEDIA, "66.25"))

    def test_la_reconversion_de_2021_queda_sin_las_dos_erratas_de_wikipedia(self):
        # xjp.cl no tiene el 30 de septiembre ni el 1 de octubre, y lo de Wikipedia era un error: quedan sin cifra.
        self.assertNotIn("2021-09-30", POR_FECHA)
        self.assertNotIn("2021-10-01", POR_FECHA)
        self.assertEqual(POR_FECHA["2021-09-29"]["ves_por_usd"], "4.2580965000")

    def test_ningun_salto_de_mas_de_tres_veces_en_una_semana(self):
        # La regla de la app (`saltaDeMas`, a siete días): una cifra así se enseñaría como un error de lectura.
        for a, b in zip(LINEAS, LINEAS[1:]):
            if (date.fromisoformat(b["fecha"]) - date.fromisoformat(a["fecha"])).days <= 7:
                r = Decimal(b["ves_por_usd"]) / Decimal(a["ves_por_usd"])
                self.assertTrue(Decimal(1) / 3 < r < 3, (a["fecha"], b["fecha"]))

    def test_los_tres_tramos_y_cuantos_dias_tiene_cada_fuente(self):
        cuenta = {f: sum(1 for l in LINEAS if l["fuente"] == f) for f in FUENTES}
        self.assertEqual(cuenta, {m.XJP: 1239, m.WIKIPEDIA: 79, m.CRIPTODOLAR: 131, m.YADIO: 276})
        # El 27 de mayo de 2025 el paralelo aún se publicó (xjp.cl 142,42, Wikipedia 142,40); el 28 ya no.
        self.assertEqual(POR_FECHA["2025-05-27"]["fuente"], m.XJP)
        self.assertEqual(POR_FECHA["2025-05-28"]["fuente"], m.CRIPTODOLAR)
        self.assertEqual(POR_FECHA["2025-10-27"]["fuente"], m.CRIPTODOLAR)
        self.assertEqual(POR_FECHA["2025-10-28"]["fuente"], m.YADIO)


class EnUnaCarpeta(unittest.TestCase):
    def setUp(self):
        carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(carpeta.cleanup)
        self.carpeta = Path(carpeta.name)

    def archivo(self, nombre, texto):
        ruta = self.carpeta / nombre
        ruta.write_text(texto, encoding="utf-8")
        return ruta


class LosLectores(EnUnaCarpeta):
    def test_xjp_lee_el_cierre_en_soberanos_y_lo_pasa_exacto(self):
        ruta = self.archivo("x.csv", "<DATE>,<OPEN>,<HIGH>,<LOW>,<CLOSE>,<VOL>\n"
                                     "03/30/2020,84000.0000,85000.0000,83000.0000,84581.0391,0\n"
                                     "10/05/2021,4180000.0000,4200000.0000,4160000.0000,4170000.0000,0\n")
        x = m.leer_xjp(ruta)
        self.assertEqual((x["2020-03-30"].valor, x["2020-03-30"].original), (Decimal("0.0845810391"), "84581.0391"))
        # La reconversión de 2021 no está aplicada en el archivo: también se divide.
        self.assertEqual(x["2021-10-05"].valor, Decimal("4.1700000000"))

    def test_wikipedia_lee_el_paralelo_y_cambia_de_escala_el_1_de_octubre_de_2021(self):
        # Con la forma del anexo: cada fila acaba en `||`, las cifras llevan «Bs.» y `&nbsp;` de miles, y un mes
        # sin ese día es una celda de tres columnas.
        texto = (
            "== Tabla cambiaria diaria 2021==\n{|class=\"wikitable\"\n|-\n"
            "| colspan=\"3\" | MES DE SEPTIEMBRE ||colspan=\"3\" | MES DE OCTUBRE ||\n|-\n"
            "|  29  || Bs. 4&nbsp;138&nbsp;617.56 || Bs. 4&nbsp;467&nbsp;830.91 ||  4  || 4,18 || 4,19 ||\n|-\n"
            "|  30  ||  sábado.  || sábado  ||  5  || 4,17 || 3,98<ref Name= X/> ||\n|-\n"
            "|  31  || colspan=\"3\" align=\"center\" |  ||  31  || 4,30 || 4,40 ||\n|}\n\n== Otra ==\n"
        )
        w, raras = m.leer_wikipedia(self.archivo("w.wikitext", texto))
        self.assertEqual((w["2021-09-29"].valor, w["2021-09-29"].original), (Decimal("4.46783091"), "4467830.91"))
        self.assertEqual((w["2021-10-04"].valor, w["2021-10-04"].original), (Decimal("4.19"), None))
        self.assertEqual(w["2021-10-05"].valor, Decimal("3.98"))
        self.assertNotIn("2021-09-30", w)
        # La fila corrida pierde el 31 de octubre, pero no lo pone en otro día.
        self.assertEqual(sorted(w), ["2021-09-29", "2021-10-04", "2021-10-05"])
        self.assertEqual(raras, [])

    def test_wikipedia_no_lee_lo_que_puede_leerse_de_dos_maneras(self):
        self.assertIsNone(m.cifra_de_wikipedia("28.041"))
        self.assertIsNone(m.cifra_de_wikipedia("4.138.617,56"))
        # Un espacio por coma, como el anexo el 2022-10-19: los miles van de tres en tres, así que no son 888.
        self.assertIsNone(m.cifra_de_wikipedia("8 88"))
        self.assertIsNone(m.cifra_de_wikipedia("4 0419 16.62"))
        self.assertEqual(m.cifra_de_wikipedia("999,99"), "999.99")
        self.assertEqual(m.cifra_de_wikipedia("5035381"), "5035381")
        self.assertEqual(m.cifra_de_wikipedia("1 821 534.67"), "1821534.67")
        self.assertEqual(m.cifra_de_wikipedia("1 821 534"), "1821534")

    def test_wikipedia_con_un_mes_de_cuatro_columnas_y_una_tabla_que_acaba_sin_raya(self):
        # Como marzo de 2026: una columna «*Promedio €» después del paralelo. Y la fila del 31, con febrero sin 31
        # en una celda de tres columnas, que es la última de su tabla y no acaba en `||`.
        texto = (
            "== Tabla cambiaria diaria 2026==\n{|class=\"wikitable\"\n!colspan=\"7\" | Primer cuatrimestre 2026\n|-\n"
            "| colspan=\"3\" | MES DE FEBRERO || colspan=\"4\" | MES DE MARZO\n|-\n"
            "|  DÍA  ||<center>BCV<ref Name= X/>  ||  PARALELO  ||  DÍA  || BCV || PARALELO || *Promedio €\n|-\n"
            "|  2  || Bs. 370.25 ||  Bs. 525.00  ||  2  || Bs. 419.08 ||  Bs. 605.40|| Bs. 550.53\n|-\n"
            "| colspan=\"3\" style=\"background:DarkSlateBlue | ||  31  || Bs. 480.00 || Bs. 650.10\n|}\n"
            "El 1 de junio de 2025 son detenidas 25 personas.\n\n== Otra ==\n"
        )
        w, raras = m.leer_wikipedia(self.archivo("w.wikitext", texto))
        self.assertEqual({d: str(c.valor) for d, c in w.items()}, {"2026-02-02": "525.00", "2026-03-02": "605.40", "2026-03-31": "650.10"})
        self.assertEqual(raras, [])

    def test_criptodolar_es_una_foto_por_dia_de_caracas_la_ultima(self):
        ruta = self.archivo("c.json", json.dumps({"prices": [
            {"price": 146.15000000000001, "createdAt": "2025-05-27T23:13:00.000Z"},
            {"price": 140.0, "createdAt": "2025-05-27T22:00:00.000Z"},
            # A la 1 de la madrugada UTC aún es el día anterior en Caracas.
            {"price": 141.2, "createdAt": "2025-05-29T01:10:00.000Z"},
        ]}))
        c = m.leer_criptodolar(ruta)
        self.assertEqual(c["2025-05-27"].valor, Decimal("146.15000000"))
        self.assertEqual(c["2025-05-28"].valor, Decimal("141.20000000"))
        self.assertNotIn("2025-05-29", c)

    def test_yadio_redondea_a_ocho_decimales(self):
        ruta = self.archivo("y.json", json.dumps([{"date": "10/28/2025", "rate": 309.4533749128702}]))
        self.assertEqual(m.leer_yadio(ruta)["2025-10-28"].valor, Decimal("309.45337491"))


class LasErratas(unittest.TestCase):
    def serie(self, cifras):
        inicio = date(2022, 10, 17)
        return {(inicio + timedelta(days=i)).isoformat(): m.Cifra(Decimal(c)) for i, c in enumerate(cifras)}

    def test_una_cifra_suelta_que_se_va_entre_dos_que_casan_es_una_errata(self):
        self.assertEqual(m.erratas_de("w", self.serie(["8.7", "8.77", "888", "8.82", "8.9"])), {("w", "2022-10-19")})

    def test_un_movimiento_de_verdad_no_lo_es(self):
        # Sube y se queda: la siguiente no casa con la anterior.
        self.assertEqual(m.erratas_de("w", self.serie(["135.26", "142.42", "146.15", "146.0"])), set())


class LaRecopilacion(unittest.TestCase):
    def test_elige_por_tramo_y_pone_al_lado_lo_que_dicen_las_demas(self):
        series = {
            m.XJP: {"2025-05-27": m.Cifra(Decimal("142.4200000000"), "142420000.0000"), "2025-05-28": m.Cifra(Decimal("142.42"))},
            m.WIKIPEDIA: {"2025-05-27": m.Cifra(Decimal("142.40"))},
            m.CRIPTODOLAR: {"2025-05-24": m.Cifra(Decimal("132.89")), "2025-05-28": m.Cifra(Decimal("141.20"))},
            m.YADIO: {},
        }
        obtenido = {f: "2026-10-27T15:00:00+00:00" for f in series}
        lineas = {l["fecha"]: l for l in m.recopilar(series, obtenido)}
        self.assertEqual(lineas["2025-05-27"]["fuente"], m.XJP)
        self.assertEqual(lineas["2025-05-27"]["cifra_original"], "142420000.0000")
        self.assertEqual(lineas["2025-05-27"]["testigos"], {m.WIKIPEDIA: "142.40"})
        self.assertEqual(lineas["2025-05-28"]["fuente"], m.CRIPTODOLAR)
        self.assertEqual(lineas["2025-05-28"]["testigos"], {m.XJP: "142.42"})
        # Un sábado del paralelo no se rellena con CriptoDólar.
        self.assertNotIn("2025-05-24", lineas)


if __name__ == "__main__":
    unittest.main()
