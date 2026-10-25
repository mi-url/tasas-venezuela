"""Las pruebas del registrador, con respuestas reales de cada fuente.

Todas las respuestas de `pruebas/respuestas/` se copiaron de las fuentes de
verdad el 2026-10-25, no se inventaron: la portada del BCV de ese domingo y su
certificado, los anuncios de Binance de los dos lados, CoinGecko, el Banco
Central Europeo y dolarapi. Un doble con otra forma que el dato real mide otra
cosa. Las pocas cifras inventadas se dicen donde se usan, y existen para
pillar algo que una respuesta real no pilla.

Ninguna prueba sale a internet.
"""

import hashlib
import io
import json
import re
import ssl
import time
import unittest
import urllib.error
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from pathlib import Path
from unittest import mock

import registrar
from registrar import CARACAS, FuenteCaida

RESPUESTAS = Path(__file__).parent / "pruebas" / "respuestas"


def respuesta(nombre: str) -> bytes:
    return (RESPUESTAS / nombre).read_bytes()


def en_caracas(dia: int, hora: int, minuto: int = 0) -> datetime:
    """Un momento de octubre de 2026 en Caracas. El 23 fue viernes."""
    return datetime(2026, 10, dia, hora, minuto, tzinfo=CARACAS)


def texto(momento: datetime) -> str:
    return momento.astimezone(timezone.utc).isoformat(timespec="seconds")


class FuentesDeMentira:
    """Contesta como contestaron las fuentes el 2026-10-25, y apunta lo que se le pide.

    `caidas` son las fuentes que esta vez no contestan; `otras` cambia lo que
    contesta una fuente.
    """

    def __init__(self, caidas=(), otras=None):
        self.caidas = set(caidas)
        self.otras = otras or {}
        self.pedidos = []

    def __call__(self, url, *, metodo="GET", cuerpo=None):
        self.pedidos.append((url, cuerpo))
        if "bcv.org.ve" in url:
            return self._o("bcv", "bcv-2026-10-25.html")
        if "binance" in url:
            lado = "venta" if cuerpo["tradeType"] == "SELL" else "compra"
            return self._o(f"binance-{lado}", f"binance-{lado}-100000.json")
        if "coingecko" in url:
            return self._o("coingecko", "coingecko.json")
        if "frankfurter" in url:
            return self._o("frankfurter", "frankfurter.json")
        if url.endswith("/dolares/oficial"):
            return self._o("dolarapi-dolar", "dolarapi-oficial.json")
        if url.endswith("/euros"):
            return self._o("dolarapi-euros", "dolarapi-euros.json")
        raise AssertionError(f"nadie esperaba {url}")

    def _o(self, fuente, nombre):
        if fuente in self.caidas or fuente.split("-")[0] in self.caidas:
            raise FuenteCaida(f"{fuente} no contestó")
        if fuente in self.otras:
            return self.otras[fuente]
        return respuesta(nombre)


class SinTope(unittest.TestCase):
    """Cada prueba empieza sin el tope de tiempo de una pasada anterior."""

    def setUp(self):
        registrar._LIMITE = None


# ---------------------------------------------------------------------------
# EL BCV
# ---------------------------------------------------------------------------


class LaPaginaDelBCV(SinTope):
    html = respuesta("bcv-2026-10-25.html").decode("utf-8")

    def test_lee_el_dolar_el_euro_y_la_fecha_valor_de_la_pagina_real(self):
        leido = registrar.leer_pagina_del_bcv(self.html)
        self.assertEqual(leido["ves_por_usd"], "887.30200000")
        self.assertEqual(leido["ves_por_eur"], "994.03555758")
        self.assertEqual(leido["fecha_valor"], "2026-10-27")
        self.assertEqual(leido["fuente"], "bcv.org.ve")

    def test_sin_fecha_valor_no_devuelve_nada(self):
        with self.assertRaises(FuenteCaida):
            registrar.leer_pagina_del_bcv(self.html.replace("Fecha Valor:", "Fecha:"))

    def test_sin_el_euro_no_devuelve_media_publicacion(self):
        with self.assertRaises(FuenteCaida):
            registrar.leer_pagina_del_bcv(self.html.replace('id="euro"', 'id="otra"'))

    def test_las_cifras_venezolanas_se_leen_sin_tocar_un_digito(self):
        html = (
            '<div id="dolar"><strong class="strong-tb"> 1.234,56789012</strong></div>'
            '<div id="euro"><strong class="strong-tb">1.400,00000001 </strong></div>'
            'Fecha Valor: <span content="2026-11-02T00:00:00-04:00">Lunes</span>'
        )
        leido = registrar.leer_pagina_del_bcv(html)
        self.assertEqual(leido["ves_por_usd"], "1234.56789012")
        self.assertEqual(leido["ves_por_eur"], "1400.00000001")


class CuandoSeMiraElBCV(SinTope):
    """La regla de Antonio: cada media hora desde la tarde, hasta que la página da la nueva."""

    def antes(self, visto, consultado, visto_por="bcv.org.ve"):
        return {"publicado_visto": texto(visto), "consultado": texto(consultado), "visto_por": visto_por}

    def test_la_primera_vez_se_mira_siempre(self):
        self.assertTrue(registrar.toca_mirar_bcv({}, en_caracas(26, 11)))

    def test_al_mediodia_no(self):
        antes = self.antes(en_caracas(25, 16, 17), en_caracas(26, 7, 47))
        self.assertFalse(registrar.toca_mirar_bcv(antes, en_caracas(26, 12, 17)))

    def test_desde_las_tres_y_media_se_mira(self):
        antes = self.antes(en_caracas(22, 16, 17), en_caracas(23, 7, 47))
        self.assertFalse(registrar.toca_mirar_bcv(antes, en_caracas(23, 15, 17)))
        self.assertTrue(registrar.toca_mirar_bcv(antes, en_caracas(23, 15, 47)))

    def test_y_se_sigue_mirando_hasta_que_aparece(self):
        antes = self.antes(en_caracas(22, 16, 17), en_caracas(23, 18, 17))
        self.assertTrue(registrar.toca_mirar_bcv(antes, en_caracas(23, 18, 47)))
        self.assertTrue(registrar.toca_mirar_bcv(antes, en_caracas(23, 23, 47)))

    def test_cuando_la_pagina_ya_la_dio_no_se_vuelve_a_mirar_esa_tarde(self):
        antes = self.antes(en_caracas(23, 16, 47), en_caracas(23, 16, 47))
        self.assertFalse(registrar.toca_mirar_bcv(antes, en_caracas(23, 17, 17)))
        self.assertFalse(registrar.toca_mirar_bcv(antes, en_caracas(23, 21, 47)))

    def test_por_la_noche_un_vistazo_mas_por_si_la_corrigio(self):
        antes = self.antes(en_caracas(23, 16, 47), en_caracas(23, 16, 47))
        self.assertTrue(registrar.toca_mirar_bcv(antes, en_caracas(23, 22, 17)))
        despues = self.antes(en_caracas(23, 16, 47), en_caracas(23, 22, 17))
        self.assertFalse(registrar.toca_mirar_bcv(despues, en_caracas(23, 22, 47)))

    def test_si_la_dio_dolarapi_se_sigue_mirando_la_pagina(self):
        # Caso C de la revisión: dolarapi no dice cuándo publicó el BCV.
        antes = self.antes(en_caracas(23, 15, 47), en_caracas(23, 15, 17), visto_por="dolarapi")
        self.assertTrue(registrar.toca_mirar_bcv(antes, en_caracas(23, 16, 47)))
        self.assertTrue(registrar.toca_mirar_bcv(antes, en_caracas(23, 22, 17)))

    def test_un_sabado_se_mira_aunque_no_vaya_a_haber_nada(self):
        antes = self.antes(en_caracas(23, 16, 47), en_caracas(24, 7, 47))
        self.assertTrue(registrar.toca_mirar_bcv(antes, en_caracas(24, 16, 17)))

    def test_de_madrugada_no(self):
        antes = self.antes(en_caracas(23, 16, 47), en_caracas(23, 23, 47))
        self.assertFalse(registrar.toca_mirar_bcv(antes, en_caracas(24, 2, 17)))

    def test_por_la_manana_un_solo_vistazo(self):
        antes = self.antes(en_caracas(23, 16, 47), en_caracas(23, 23, 47))
        self.assertTrue(registrar.toca_mirar_bcv(antes, en_caracas(24, 7, 47)))
        despues = self.antes(en_caracas(23, 16, 47), en_caracas(24, 7, 47))
        self.assertFalse(registrar.toca_mirar_bcv(despues, en_caracas(24, 8, 17)))


class DesdeCuandoRige(SinTope):
    vieja = {"ves_por_usd": "886.22710000", "ves_por_eur": "993.08836371", "fecha_valor": "2026-10-23",
             "fuente": "bcv.org.ve", "publicado_visto": texto(en_caracas(22, 16, 47)),
             "no_estaba_a_las": texto(en_caracas(22, 16, 17)), "visto_por": "bcv.org.ve",
             "consultado": texto(en_caracas(23, 16, 17))}
    nueva = {"ves_por_usd": "887.30200000", "ves_por_eur": "994.03555758", "fecha_valor": "2026-10-27",
             "fuente": "bcv.org.ve"}

    def test_una_publicacion_nueva_rige_desde_que_se_vio(self):
        bcv = registrar.anotar_bcv(self.nueva, self.vieja, en_caracas(23, 16, 47))
        self.assertEqual(bcv["publicado_visto"], texto(en_caracas(23, 16, 47)))
        self.assertEqual(bcv["no_estaba_a_las"], texto(en_caracas(23, 16, 17)))
        self.assertEqual(bcv["visto_por"], "bcv.org.ve")

    def test_la_misma_publicacion_conserva_su_momento(self):
        ya = registrar.anotar_bcv(self.nueva, self.vieja, en_caracas(23, 16, 47))
        otra_vez = registrar.anotar_bcv(self.nueva, ya, en_caracas(24, 7, 47))
        self.assertEqual(otra_vez["publicado_visto"], texto(en_caracas(23, 16, 47)))
        self.assertEqual(otra_vez["no_estaba_a_las"], texto(en_caracas(23, 16, 17)))
        self.assertEqual(otra_vez["consultado"], texto(en_caracas(24, 7, 47)))

    def test_una_correccion_sin_cambiar_la_fecha_es_nueva(self):
        corregida = dict(self.vieja, ves_por_usd="886.30000000")
        bcv = registrar.anotar_bcv(corregida, self.vieja, en_caracas(23, 18, 17))
        self.assertEqual(bcv["publicado_visto"], texto(en_caracas(23, 18, 17)))

    def test_una_fecha_valor_anterior_se_rechaza(self):
        ya = registrar.anotar_bcv(self.nueva, self.vieja, en_caracas(23, 16, 47))
        with self.assertRaises(FuenteCaida):
            registrar.anotar_bcv(self.vieja, ya, en_caracas(24, 16, 17))

    def test_dolarapi_con_la_misma_publicacion_no_trae_nada(self):
        # Caso A: no mueve `consultado`, así que el hueco de cuando no estaba sigue siendo verdad.
        mismo = dict(self.vieja, fuente="dolarapi")
        self.assertIsNone(registrar.anotar_bcv(mismo, self.vieja, en_caracas(23, 16, 47)))

    def test_dolarapi_no_pisa_una_correccion_de_la_pagina(self):
        # Caso D: la página corrigió con la misma fecha; dolarapi sigue con la cifra sin corregir.
        corregida = registrar.anotar_bcv(dict(self.vieja, ves_por_usd="886.30000000"), self.vieja,
                                         en_caracas(23, 18, 17))
        sin_corregir = dict(self.vieja, fuente="dolarapi")
        self.assertIsNone(registrar.anotar_bcv(sin_corregir, corregida, en_caracas(23, 19, 17)))

    def test_dolarapi_con_una_publicacion_nueva_queda_marcado_hasta_la_siguiente(self):
        # Caso B: la vio primero dolarapi; la página la confirma después y la marca no se pierde.
        de_dolarapi = registrar.anotar_bcv(dict(self.nueva, fuente="dolarapi"), self.vieja, en_caracas(24, 7, 47))
        self.assertEqual(de_dolarapi["visto_por"], "dolarapi")
        self.assertEqual(de_dolarapi["consultado"], self.vieja["consultado"])
        confirmada = registrar.anotar_bcv(self.nueva, de_dolarapi, en_caracas(24, 16, 17))
        self.assertEqual(confirmada["visto_por"], "dolarapi")
        self.assertEqual(confirmada["publicado_visto"], texto(en_caracas(24, 7, 47)))
        self.assertTrue(registrar.bloques_del_bcv(confirmada)["ves_por_usd_bcv"]["respaldo"])

    def test_sin_fecha_valor_no_se_anota(self):
        # Caso F.
        with self.assertRaises(FuenteCaida):
            registrar.anotar_bcv(dict(self.nueva, fecha_valor=None, fuente="dolarapi"), self.vieja,
                                 en_caracas(24, 7, 47))

    def test_los_bloques_conservan_lo_que_lee_la_app_anterior(self):
        bcv = registrar.anotar_bcv(self.nueva, self.vieja, en_caracas(23, 16, 47))
        bloques = registrar.bloques_del_bcv(bcv)
        dolar, euro = bloques["ves_por_usd_bcv"], bloques["ves_por_eur_bcv"]
        for clave in ("ves_por_usd", "fuente", "fecha_valor", "contrastada", "obtenido"):
            self.assertIn(clave, dolar)
        for clave in ("valor", "fuente", "fecha_valor", "obtenido"):
            self.assertIn(clave, euro)
        self.assertEqual(dolar["ves_por_usd"], "887.30200000")
        self.assertEqual(euro["valor"], "994.03555758")
        self.assertIsNone(dolar["contrastada"])
        self.assertFalse(dolar["respaldo"])


class ElRespaldoDeDolarapi(SinTope):

    def test_lee_el_dolar_y_el_euro_reales(self):
        leido = registrar.leer_dolarapi(json.loads(respuesta("dolarapi-oficial.json")),
                                        json.loads(respuesta("dolarapi-euros.json")))
        self.assertEqual(leido["ves_por_usd"], "886.22710000")
        self.assertEqual(leido["ves_por_eur"], "993.08836371")
        self.assertEqual(leido["fecha_valor"], "2026-10-23")

    def test_sin_fecha_no_vale(self):
        dolar = json.loads(respuesta("dolarapi-oficial.json"))
        dolar["fechaActualizacion"] = None
        with self.assertRaises(FuenteCaida):
            registrar.leer_dolarapi(dolar, json.loads(respuesta("dolarapi-euros.json")))

    def test_el_dolar_y_el_euro_de_dias_distintos_no_valen(self):
        dolar = json.loads(respuesta("dolarapi-oficial.json"))
        dolar["fechaActualizacion"] = "2026-10-22T00:00:00-04:00"
        with self.assertRaises(FuenteCaida):
            registrar.leer_dolarapi(dolar, json.loads(respuesta("dolarapi-euros.json")))

    def test_con_otra_forma_no_tumba_nada(self):
        with self.assertRaises(FuenteCaida):
            registrar.leer_dolarapi(json.loads(respuesta("dolarapi-oficial.json")), {"no": "es una lista"})


# ---------------------------------------------------------------------------
# BINANCE
# ---------------------------------------------------------------------------


class TasaDeMercado(SinTope):

    def test_la_venta_es_la_mediana_de_los_anuncios_reales(self):
        precios = registrar.precios_de_binance(json.loads(respuesta("binance-venta-100000.json")))
        resumen = registrar.resumen_de_binance(precios)
        # Los diez del 2026-10-25, ordenados: el quinto y el sexto son 1003,001 y 1003,100.
        self.assertEqual(resumen["ves_por_usdt"], "1003.05050000")
        self.assertEqual(resumen["muestras"], 10)

    def test_un_anuncio_raro_no_mueve_la_mediana(self):
        # Sin filtro de monto, el primero estaba a 980,54 con un límite de 300 a 400 bolívares.
        precios = registrar.precios_de_binance(json.loads(respuesta("binance-compra-sin-monto.json")))
        self.assertEqual(precios[0], Decimal("980.540"))
        mediana = Decimal(registrar.resumen_de_binance(precios)["ves_por_usdt"])
        self.assertGreater(mediana, Decimal("1005"))

    def test_con_menos_de_cinco_anuncios_no_se_publica(self):
        with self.assertRaises(FuenteCaida):
            registrar.resumen_de_binance([Decimal("1000")] * 4)

    def test_se_pide_con_lo_que_valen_cien_dolares(self):
        fuentes = FuentesDeMentira()
        anterior = {"ves_por_usdt_mercado": {"ves_por_usdt": "1005.46000000"}}
        with mock.patch.object(registrar, "_pedir", fuentes):
            mercado = registrar.mercado_desde_binance(anterior)
        cuerpos = [c for u, c in fuentes.pedidos if "binance" in u]
        self.assertEqual([c["tradeType"] for c in cuerpos], ["SELL", "BUY"])
        self.assertTrue(all(c["transAmount"] == "100546" for c in cuerpos))
        self.assertEqual(mercado["monto_bs"], "100546")
        self.assertIsNotNone(mercado["compra"])

    def test_sin_tasa_anterior_no_se_filtra_y_se_dice(self):
        fuentes = FuentesDeMentira()
        with mock.patch.object(registrar, "_pedir", fuentes):
            mercado = registrar.mercado_desde_binance({})
        self.assertTrue(all("transAmount" not in c for u, c in fuentes.pedidos if "binance" in u))
        self.assertIn("sin filtro", mercado["metodo"])

    def test_si_la_compra_falla_la_venta_se_publica_igual(self):
        fuentes = FuentesDeMentira(caidas={"binance-compra"})
        with mock.patch.object(registrar, "_pedir", fuentes):
            mercado = registrar.mercado_desde_binance({"ves_por_usdt_mercado": {"ves_por_usdt": "1005.46"}})
        self.assertEqual(mercado["ves_por_usdt"], "1003.05050000")
        self.assertIsNone(mercado["compra"])
        self.assertIn("fallo_compra", mercado)


# ---------------------------------------------------------------------------
# LAS CIFRAS EXACTAS
# ---------------------------------------------------------------------------


class NadaPasaPorComaFlotante(SinTope):

    def test_las_criptomonedas_reales_se_guardan_como_vinieron(self):
        with mock.patch.object(registrar, "_pedir", FuentesDeMentira()):
            cripto = registrar.criptomonedas()
        self.assertEqual(cripto["usd_por"], {"BTC": "80389", "USDT": "0.998985"})
        with localcontext() as ctx:
            ctx.prec = 40
            esperado = f"{Decimal(1) / Decimal('0.998985'):.12f}"
        self.assertEqual(cripto["por_usd"]["USDT"], esperado)

    def test_una_cifra_que_un_float_no_puede_guardar_sale_entera(self):
        # Inventada a propósito: 0,1 con 34 decimales. Un float la deja en 0.1 y esta prueba se pone roja.
        cifra = "0.1000000000000000055511151231257827"
        fuentes = FuentesDeMentira(otras={"coingecko": f'{{"tether": {{"usd": {cifra}}}}}'.encode()})
        with mock.patch.object(registrar, "_pedir", fuentes):
            cripto = registrar.criptomonedas()
        self.assertEqual(cripto["usd_por"]["USDT"], cifra)

    def test_las_internacionales_tal_cual(self):
        with mock.patch.object(registrar, "_pedir", FuentesDeMentira()):
            inter = registrar.internacionales()
        self.assertEqual(inter["por_usd"]["EUR"], "0.89342000")
        self.assertEqual(inter["por_usd"]["JPY"], "156.80000000")
        self.assertEqual(inter["fecha_valor"], "2026-10-23")

    def test_una_cifra_que_no_es_positiva_se_rechaza(self):
        for mala in ("0", "-1", "abc", "NaN", "Infinity"):
            with self.assertRaises(FuenteCaida):
                registrar._cifra(mala)

    def test_el_json_se_lee_con_decimales_exactos(self):
        self.assertEqual(registrar._json(b'{"x": 0.1}')["x"], Decimal("0.1"))

    def test_una_respuesta_que_no_es_json_es_una_fuente_caida(self):
        with self.assertRaises(FuenteCaida):
            registrar._json(b"<html>Service Unavailable</html>")


# ---------------------------------------------------------------------------
# EL CERTIFICADO DEL BCV
# ---------------------------------------------------------------------------


class ElCertificadoDelBCV(SinTope):
    # Huellas de los dos intermedios de Sectigo, sacados de las direcciones que trae
    # el certificado del BCV, y comprobados el 2026-10-25 conectando a la página.
    DV_R36 = "8C54C334B66BA4E426772AF4A3F9136C19A1AEC729FDB28C535C07A5A4EF22E0"
    R46_POR_USERTRUST = "92F351BF3D54164DFA8DD8F9E1139D3150349786485D2B9EECD00E2971C1E6C5"

    def intermedios(self):
        pem = registrar.INTERMEDIOS_DEL_BCV.read_text()
        return re.findall(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", pem, re.S)

    def test_lleva_los_dos_intermedios_que_el_bcv_no_manda(self):
        huellas = [hashlib.sha256(ssl.PEM_cert_to_DER_cert(b)).hexdigest().upper() for b in self.intermedios()]
        self.assertEqual(huellas, [self.DV_R36, self.R46_POR_USERTRUST])

    def test_no_acepta_una_cadena_a_medias_aunque_python_la_traiga_encendida(self):
        # Python 3.13 enciende la cadena a medias por defecto; se simula aquí en cualquier versión.
        original = ssl.create_default_context

        def con_la_cadena_a_medias(*a, **k):
            ctx = original(*a, **k)
            ctx.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
            return ctx

        with mock.patch("ssl.create_default_context", con_la_cadena_a_medias):
            ctx = registrar.contexto_tls()
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(ctx.check_hostname)
        self.assertFalse(ctx.verify_flags & ssl.VERIFY_X509_PARTIAL_CHAIN)

    def test_lee_de_donde_se_baja_el_intermedio_del_certificado_real(self):
        der = ssl.PEM_cert_to_DER_cert(respuesta("certificado-del-bcv-2026-10-25.pem").decode())
        self.assertEqual(registrar.emisores_del_certificado(der),
                         ["http://crt.sectigo.com/SectigoPublicServerAuthenticationCADVR36.crt"])

    def test_si_falta_un_intermedio_lo_va_a_buscar(self):
        der_del_bcv = ssl.PEM_cert_to_DER_cert(respuesta("certificado-del-bcv-2026-10-25.pem").decode())
        der_del_intermedio = ssl.PEM_cert_to_DER_cert(self.intermedios()[0])
        registrar._TLS = None
        with mock.patch.object(registrar, "certificado_del_servidor", return_value=der_del_bcv), \
             mock.patch.object(registrar, "_pedir", return_value=der_del_intermedio) as pedir:
            self.assertTrue(registrar.completar_la_cadena("www.bcv.org.ve"))
        pedir.assert_called_once_with("http://crt.sectigo.com/SectigoPublicServerAuthenticationCADVR36.crt")
        registrar._TLS = None

    def test_un_fallo_de_certificado_intenta_completar_y_reintenta(self):
        llamadas = []

        def pedir(url, **k):
            llamadas.append(url)
            if len(llamadas) == 1:
                raise FuenteCaida(f"{url} no respondió: [SSL: CERTIFICATE_VERIFY_FAILED]")
            return b"pagina"

        with mock.patch.object(registrar, "_pedir", pedir), \
             mock.patch.object(registrar, "completar_la_cadena", return_value=True) as completar:
            self.assertEqual(registrar._pedir_completando("https://www.bcv.org.ve/"), b"pagina")
        completar.assert_called_once_with("www.bcv.org.ve")
        self.assertEqual(len(llamadas), 2)

    def test_otro_fallo_no_intenta_completar_nada(self):
        with mock.patch.object(registrar, "_pedir", side_effect=FuenteCaida("respondió 503")), \
             mock.patch.object(registrar, "completar_la_cadena") as completar:
            with self.assertRaises(FuenteCaida):
                registrar._pedir_completando("https://www.bcv.org.ve/")
        completar.assert_not_called()


class LosReintentosYElTope(SinTope):

    def test_un_fallo_de_red_se_reintenta_y_un_429_no(self):
        llamadas = []

        class Respuesta:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b"bien"

        def red(peticion, timeout, context):
            llamadas.append(peticion.full_url)
            if len(llamadas) < 3:
                raise urllib.error.URLError("sin red")
            return Respuesta()

        with mock.patch("urllib.request.urlopen", red), mock.patch("time.sleep"):
            self.assertEqual(registrar._pedir("https://ejemplo.test/"), b"bien")
        self.assertEqual(len(llamadas), 3)

        def demasiadas(peticion, timeout, context):
            raise urllib.error.HTTPError(peticion.full_url, 429, "Too Many Requests", {}, io.BytesIO())

        with mock.patch("urllib.request.urlopen", demasiadas), mock.patch("time.sleep") as espera:
            with self.assertRaises(FuenteCaida):
                registrar._pedir("https://ejemplo.test/")
        espera.assert_not_called()

    def test_acabado_el_tiempo_de_la_pasada_no_se_pide_nada_mas(self):
        registrar._LIMITE = time.monotonic() + 1
        with mock.patch("urllib.request.urlopen") as red:
            with self.assertRaises(FuenteCaida):
                registrar._pedir("https://ejemplo.test/")
        red.assert_not_called()


# ---------------------------------------------------------------------------
# UNA PASADA ENTERA
# ---------------------------------------------------------------------------


class UnaPasadaEntera(SinTope):
    de_antes = json.loads(respuesta("tasas-de-la-version-anterior.json"))

    def pasada(self, anterior, ahora, **fuentes):
        with mock.patch.object(registrar, "_pedir", FuentesDeMentira(**fuentes)):
            return registrar.registrar(anterior, ahora)

    def test_la_primera_pasada_despues_de_la_version_anterior(self):
        ahora = en_caracas(25, 17, 47)
        salida = self.pasada(self.de_antes, ahora)
        self.assertNotIn("fallos", salida)
        dolar = salida["ves_por_usd_bcv"]
        self.assertEqual(dolar["ves_por_usd"], "887.30200000")
        self.assertEqual(dolar["fecha_valor"], "2026-10-27")
        self.assertEqual(dolar["fuente"], "bcv.org.ve")
        self.assertEqual(dolar["publicado_visto"], texto(ahora))
        # La versión anterior no guardaba cuándo miró: no se sabe desde cuándo estaba, y se dice.
        self.assertIsNone(dolar["no_estaba_a_las"])
        self.assertEqual(salida["ves_por_eur_bcv"]["valor"], "994.03555758")
        self.assertEqual(salida["ves_por_usdt_mercado"]["ves_por_usdt"], "1003.05050000")
        self.assertIn("compra", salida["ves_por_usdt_mercado"])
        self.assertEqual(salida["criptomonedas"]["usd_por"]["BTC"], "80389")
        self.assertEqual(salida["internacionales"]["por_usd"]["EUR"], "0.89342000")

    def test_las_claves_que_lee_la_app_anterior_siguen_ahi(self):
        salida = self.pasada(self.de_antes, en_caracas(25, 17, 47))
        self.assertIn("actualizado", salida)
        self.assertIsInstance(salida["ves_por_usdt_mercado"]["ves_por_usdt"], str)
        self.assertIn("fuente", salida["ves_por_usdt_mercado"])
        for bloque in ("internacionales", "criptomonedas"):
            self.assertIn("por_usd", salida[bloque])
            self.assertIn("fuente", salida[bloque])

    def test_una_fuente_caida_repite_lo_anterior_con_su_hora_de_entonces(self):
        salida = self.pasada(self.de_antes, en_caracas(25, 17, 47), caidas={"coingecko"})
        self.assertEqual(salida["criptomonedas"], self.de_antes["criptomonedas"])
        self.assertTrue(any(f.startswith("cripto") for f in salida["fallos"]))

    def test_una_respuesta_rara_no_tumba_la_pasada(self):
        salida = self.pasada(self.de_antes, en_caracas(25, 17, 47),
                             otras={"coingecko": b"<html>Bad gateway</html>", "frankfurter": b"[1, 2]"})
        self.assertEqual(salida["criptomonedas"], self.de_antes["criptomonedas"])
        self.assertEqual(salida["internacionales"], self.de_antes["internacionales"])
        self.assertEqual(salida["ves_por_usd_bcv"]["ves_por_usd"], "887.30200000")
        self.assertEqual(len(salida["fallos"]), 2)

    def test_un_error_que_nadie_esperaba_tampoco_tumba_la_pasada(self):
        fuentes = FuentesDeMentira()

        def revienta(url, **k):
            if "coingecko" in url:
                raise RuntimeError("algo que nadie previó")
            return fuentes(url, **k)

        with mock.patch.object(registrar, "_pedir", revienta):
            salida = registrar.registrar(self.de_antes, en_caracas(25, 17, 47))
        self.assertEqual(salida["criptomonedas"], self.de_antes["criptomonedas"])
        self.assertIn("cripto: RuntimeError: algo que nadie previó", salida["fallos"])
        self.assertEqual(salida["ves_por_usdt_mercado"]["ves_por_usdt"], "1003.05050000")

    def test_la_pagina_caida_no_mueve_cuando_se_miro_y_dolarapi_atrasado_no_pisa_nada(self):
        primera = self.pasada(self.de_antes, en_caracas(25, 17, 47))
        # Al día siguiente, la página no contesta y dolarapi sigue con la del 23.
        segunda = self.pasada(primera, en_caracas(26, 16, 17), caidas={"bcv"})
        self.assertEqual(segunda["ves_por_usd_bcv"], primera["ves_por_usd_bcv"])
        self.assertTrue(any("anterior a la del 2026-10-27" in f for f in segunda["fallos"]))
        # Y la pasada siguiente lo vuelve a intentar.
        self.assertTrue(registrar.toca_mirar_bcv(registrar.bcv_anterior(segunda), en_caracas(26, 16, 47)))

    def test_sin_mirar_el_bcv_se_repite_lo_que_habia(self):
        primera = self.pasada(self.de_antes, en_caracas(25, 17, 47))
        fuentes = FuentesDeMentira()
        with mock.patch.object(registrar, "_pedir", fuentes):
            segunda = registrar.registrar(primera, en_caracas(26, 11, 17))
        self.assertFalse(any("bcv" in u for u, c in fuentes.pedidos))
        self.assertEqual(segunda["ves_por_usd_bcv"], primera["ves_por_usd_bcv"])

    def test_el_banco_central_europeo_no_se_vuelve_a_pedir_si_ya_dio_el_de_hoy(self):
        previas = {"por_usd": {"EUR": "0.9"}, "fuente": "frankfurter-bce", "fecha_valor": "2026-10-26",
                   "consultado": texto(en_caracas(26, 11, 17))}
        self.assertFalse(registrar.toca_mirar_internacionales(previas, en_caracas(26, 11, 47)))
        de_ayer = dict(previas, fecha_valor="2026-10-23")
        self.assertFalse(registrar.toca_mirar_internacionales(de_ayer, en_caracas(26, 12, 17)))
        self.assertTrue(registrar.toca_mirar_internacionales(de_ayer, en_caracas(26, 13, 47)))


if __name__ == "__main__":
    unittest.main()
