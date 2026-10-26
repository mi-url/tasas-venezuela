#!/usr/bin/env python3
"""Registrador de tasas de cambio de Venezuela.

Corre solo, cada media hora, y anota a cuánto está el bolívar. Publica dos
cosas: `tasas.json` con lo último, que es lo que lee la app, y un histórico
mensual, que es lo que permite saber dentro de un año a cuánto estaba el dólar
el martes pasado — porque **ninguna fuente guarda ese histórico** y sin él las
operaciones de días anteriores no se pueden valorar bien.

Por qué existe este intermediario, en vez de que la app consulte directamente:

- Una sola consulta cada media hora en total, sin importar cuánta gente use la
  app. Si cada teléfono consultara por su cuenta, multiplicaríamos las llamadas
  por cada usuario y el endpoint de Binance —que no es oficial— acabaría
  bloqueándonos.
- Leer un archivo publicado no tiene límite ni puede bloquearse.

El servicio anterior de Antonio se cayó y estuvo seis meses sirviendo una tasa
de 339 cuando el dólar estaba en 746, sin que nadie se enterara. Aquí eso no
puede pasar: cada dato lleva de dónde salió y cuándo, y si envejece la app lo
dice.

Cuidado con las unidades. Cada clave dice **en qué unidad está** (`ves_por_usd`,
`ves_por_eur`). Mezclar "bolívares por dólar" con "dólares por bolívar" fue
exactamente el error que hacía que el motor viejo registrara ganancias de
noventa mil dólares sobre diez.

Y cuidado con los decimales: **ninguna cifra pasa por un número de coma
flotante**. Cada una se guarda tal como la dio su fuente, con `Decimal`.
"""

from __future__ import annotations

import json
import os
import re
import socket
import ssl
import statistics
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from urllib.parse import urlparse

RAIZ = Path(__file__).parent
ULTIMAS = RAIZ / "tasas.json"
HISTORICO = RAIZ / "historico"
INTERMEDIOS_DEL_BCV = RAIZ / "certificados" / "intermedios-bcv.pem"

# Caracas no cambia la hora en todo el año.
CARACAS = timezone(timedelta(hours=-4))

AGENTE = "registrador-tasas-venezuela/2.0 (+https://github.com/mi-url/tasas-venezuela)"
ESPERA = 15
INTENTOS = 3

# **Cuánto puede durar una pasada.** GitHub corta el trabajo a los 8 minutos, y
# un trabajo cortado no publica nada. Con siete consultas que reintentan, el
# peor caso se pasaría; por eso hay un tope común: a los tres minutos y medio no
# se empieza ninguna consulta más, y lo que no llegó se apunta como fallo.
DURACION_MAXIMA = 210


class FuenteCaida(Exception):
    """Una fuente no respondió o respondió algo que no se entiende."""


# ---------------------------------------------------------------------------
# PEDIR
# ---------------------------------------------------------------------------


def contexto_tls() -> ssl.SSLContext:
    """La verificación de siempre, más los dos intermedios que el BCV no manda.

    **El servidor del BCV sirve mal su cadena de certificados**: su certificado
    lo firma «Sectigo Public Server Authentication CA DV R36», y en vez de ese
    intermedio manda otro que no viene al caso. Un navegador lo arregla solo
    yendo a buscar el que falta; Python no, y por eso la página del BCV no se
    pudo leer nunca desde GitHub (`CERTIFICATE_VERIFY_FAILED`, 4.072 veces de
    4.138 entre agosto y octubre de 2026).

    El arreglo no es apagar la verificación: es darle a Python los dos eslabones
    que faltan —ese intermedio y la raíz R46 de Sectigo firmada por USERTrust—,
    sacados de las direcciones que trae el propio certificado. Y se le exige
    que la cadena llegue hasta una raíz de confianza del sistema: sin
    `VERIFY_X509_PARTIAL_CHAIN`, un intermedio añadido sirve para completar la
    cadena, nunca para darla por buena él solo. Si alguien cambiara el archivo
    por un certificado falso, la firma no cuadraría y la conexión se negaría.
    Python 3.13 enciende esa opción por defecto; aquí se apaga a propósito, en
    cualquier versión.
    """
    ctx = ssl.create_default_context()
    ctx.load_verify_locations(cafile=str(INTERMEDIOS_DEL_BCV))
    ctx.verify_flags &= ~ssl.VERIFY_X509_PARTIAL_CHAIN
    return ctx


_TLS: ssl.SSLContext | None = None
_LIMITE: float | None = None


def _tls() -> ssl.SSLContext:
    global _TLS
    if _TLS is None:
        _TLS = contexto_tls()
    return _TLS


def _queda() -> float:
    return float("inf") if _LIMITE is None else _LIMITE - time.monotonic()


def _pedir(url: str, *, metodo: str = "GET", cuerpo: dict | None = None) -> bytes:
    """Pide una dirección, con reintentos cortos si falla la red o el servidor.

    Un 429 («demasiadas peticiones») o cualquier otro 4xx no se reintenta: se
    respeta y se sale. Un fallo de red o un 5xx sí, dos veces más, esperando un
    poco más cada vez, y nunca más allá del tope de la pasada.
    """
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    cabeceras = {"User-Agent": AGENTE, "Accept": "application/json, text/html"}
    if datos is not None:
        cabeceras["Content-Type"] = "application/json"
    ultimo = None
    for intento in range(INTENTOS):
        queda = _queda()
        if queda < 3:
            raise FuenteCaida(f"{url}: se acabó el tiempo de la pasada")
        peticion = urllib.request.Request(url, data=datos, headers=cabeceras, method=metodo)
        try:
            with urllib.request.urlopen(peticion, timeout=min(ESPERA, queda), context=_tls()) as respuesta:
                return respuesta.read()
        except urllib.error.HTTPError as e:
            if e.code < 500:
                raise FuenteCaida(f"{url} respondió {e.code}") from e
            ultimo = f"{url} respondió {e.code}"
        except Exception as e:  # noqa: BLE001 — cualquier fallo de red es lo mismo aquí
            ultimo = f"{url} no respondió: {e}"
        if intento < INTENTOS - 1:
            time.sleep(min(2 * (intento + 1), max(0, _queda() - 3)))
    raise FuenteCaida(ultimo or f"{url} no respondió")


def _json(crudo: bytes):
    """JSON con los decimales exactos: `0.1` es `Decimal('0.1')`, nunca un float.

    Una respuesta que no es JSON —una página de error con código 200, una
    respuesta cortada— es una fuente caída, no un motivo para tumbar la pasada.
    """
    try:
        return json.loads(crudo, parse_float=Decimal)
    except ValueError as e:
        raise FuenteCaida(f"la respuesta no es JSON: {crudo[:80]!r}") from e


def _cifra(valor) -> Decimal:
    """Una cifra exacta y positiva, venga como texto o como número del JSON."""
    try:
        d = Decimal(str(valor))
    except (InvalidOperation, ValueError) as e:
        raise FuenteCaida(f"«{valor}» no es una cifra") from e
    if not d.is_finite() or d <= 0:
        raise FuenteCaida(f"«{valor}» no es una cifra positiva")
    return d


def _texto(d: Decimal, decimales: int = 8) -> str:
    """Una cifra de una fuente, **tal cual**, con al menos `decimales` decimales, como ya la publicaba esto.

    Las tasas del BCV traen ocho decimales y las de Binance tres: escritas así
    sólo se rellenan con ceros. **Si trae más, se escriben todos**: recortarla
    sería publicar una cifra que la fuente no dio.
    """
    if -d.as_tuple().exponent > decimales:
        return format(d, "f")
    return f"{d:.{decimales}f}"


def _redondeada(d: Decimal, decimales: int) -> str:
    """Una cifra **calculada aquí** (una dispersión, una inversa), redondeada a `decimales`.

    No es una cifra de ninguna fuente: una división no tiene escritura decimal
    finita, y hay que cortarla en algún sitio. Lo que publica una fuente va por
    `_texto`, que no redondea nunca.
    """
    return f"{d:.{decimales}f}"


def _ahora_texto(momento: datetime) -> str:
    return momento.astimezone(timezone.utc).isoformat(timespec="seconds")


def _momento(texto) -> datetime | None:
    try:
        return datetime.fromisoformat(str(texto)) if texto else None
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# EL CERTIFICADO QUE FALTE, COMO UN NAVEGADOR
# ---------------------------------------------------------------------------


def emisores_del_certificado(der: bytes) -> list[str]:
    """De dónde se baja el intermedio que firmó este certificado (su «CA Issuers»)."""
    with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as f:
        f.write(ssl.DER_cert_to_PEM_cert(der))
        nombre = f.name
    try:
        # La única forma de leer un certificado sin librerías de fuera. Es interna
        # de Python, pero existe desde hace años y el flujo fija la versión.
        datos = ssl._ssl._test_decode_cert(nombre)  # noqa: SLF001
    finally:
        os.unlink(nombre)
    return [u for u in (datos.get("caIssuers") or ()) if u.startswith(("http://", "https://"))]


def certificado_del_servidor(host: str) -> bytes:
    """El certificado que presenta un servidor, sin verificarlo.

    Sólo se usa para leer de dónde se baja su intermedio. No se le cree nada:
    lo que se baje de ahí sólo completa la cadena, y la conexión de verdad sigue
    exigiendo que llegue hasta una raíz de confianza.
    """
    sin_verificar = ssl.create_default_context()
    sin_verificar.check_hostname = False
    sin_verificar.verify_mode = ssl.CERT_NONE
    with socket.create_connection((host, 443), timeout=min(ESPERA, _queda())) as s:
        with sin_verificar.wrap_socket(s, server_hostname=host) as t:
            return t.getpeercert(binary_form=True)


def completar_la_cadena(host: str) -> bool:
    """Va a buscar el intermedio que el servidor no manda, como hace un navegador.

    **El certificado del BCV vence el 2026-11-20.** Si el nuevo lo firma otro
    intermedio que el servidor tampoco mande, los dos de
    `certificados/intermedios-bcv.pem` ya no servirán. En vez de quedarse sin la
    página hasta que alguien se dé cuenta, el registrador lee del propio
    certificado de dónde se baja su intermedio, lo baja y lo añade. Devuelve si
    añadió alguno.
    """
    añadidos = 0
    for url in emisores_del_certificado(certificado_del_servidor(host))[:2]:
        crudo = _pedir(url)
        pem = crudo.decode("ascii", errors="ignore") if b"BEGIN CERTIFICATE" in crudo else ssl.DER_cert_to_PEM_cert(crudo)
        try:
            _tls().load_verify_locations(cadata=pem)
            añadidos += 1
        except ssl.SSLError:
            continue
    return añadidos > 0


def _pedir_completando(url: str) -> bytes:
    """Como `_pedir`, pero si falla el certificado intenta completar la cadena una vez."""
    try:
        return _pedir(url)
    except FuenteCaida as e:
        if "CERTIFICATE_VERIFY_FAILED" not in str(e):
            raise
        try:
            añadio = completar_la_cadena(urlparse(url).hostname)
        except (OSError, ValueError, FuenteCaida):
            raise e from None
        if not añadio:
            raise
        return _pedir(url)


# ---------------------------------------------------------------------------
# TASA OFICIAL (BCV): DÓLAR Y EURO
# ---------------------------------------------------------------------------

PAGINA_DEL_BCV = "https://www.bcv.org.ve/"
LA_PAGINA = "bcv.org.ve"
EL_RESPALDO = "dolarapi"

_PATRON_TASA_BCV = r'id="{}".{{0,700}}?<strong[^>]*>\s*([\d.,]+)\s*</strong>'
# **Una cifra del BCV, escrita a la venezolana**: puntos de miles opcionales y coma decimal. Si el BCV la
# escribiera con punto decimal, quitarle «los puntos de miles» la multiplicaría por cien millones (887.30200000 →
# 88730200000): una cifra que no tenga esta forma no se lee. La app lee la página con el mismo patrón
# (`app2/lib/core/tasas/traer.dart`, `readBcvPage`).
_CIFRA_VENEZOLANA = re.compile(r"^\d{1,3}(\.\d{3})*,\d+$|^\d+,\d+$")
_PATRON_FECHA_VALOR = r"Fecha\s+Valor:\s*<span[^>]*content=\"(\d{4}-\d{2}-\d{2})T"


def leer_pagina_del_bcv(html: str) -> dict:
    """El dólar, el euro y la fecha valor, leídos de la portada del BCV.

    Los tres salen del mismo vistazo, así que siempre son de la misma
    publicación. El BCV escribe las cifras al estilo venezolano —`887,30200000`,
    punto de miles y coma decimal— y aquí se guardan con punto decimal y sin
    tocar un dígito. **Una cifra sin la coma decimal de siempre no se lee**
    (`_CIFRA_VENEZOLANA`).

    Si falta cualquiera de los tres, no se devuelve nada: una publicación a
    medias es peor que ninguna.
    """
    def tasa(codigo: str) -> str:
        m = re.search(_PATRON_TASA_BCV.format(codigo), html, re.S)
        if not m:
            raise FuenteCaida(f"no se encontró el {codigo} en la página del BCV")
        escrita = m.group(1).strip()
        if not _CIFRA_VENEZOLANA.match(escrita):
            raise FuenteCaida(f"el BCV escribe «{escrita}», sin la coma decimal de siempre")
        return _texto(_cifra(escrita.replace(".", "").replace(",", ".")))

    m = re.search(_PATRON_FECHA_VALOR, html, re.S)
    if not m:
        raise FuenteCaida("no se encontró la fecha valor en la página del BCV")
    return {"ves_por_usd": tasa("dolar"), "ves_por_eur": tasa("euro"), "fecha_valor": m.group(1), "fuente": LA_PAGINA}


def bcv_desde_la_pagina() -> dict:
    return leer_pagina_del_bcv(_pedir_completando(PAGINA_DEL_BCV).decode("utf-8", errors="ignore"))


def leer_dolarapi(dolar, euros) -> dict:
    """El dólar y el euro oficiales de dolarapi, sólo si son de la misma publicación."""
    try:
        euro = next((c for c in euros if c.get("fuente") == "oficial"), None)
        fecha_dolar = (dolar.get("fechaActualizacion") or "")[:10]
        fecha_euro = ((euro or {}).get("fechaActualizacion") or "")[:10]
        if not dolar.get("promedio") or not euro or not euro.get("promedio"):
            raise FuenteCaida("dolarapi no trajo el dólar y el euro oficiales")
    except (AttributeError, TypeError) as e:
        raise FuenteCaida(f"dolarapi contestó con otra forma: {e}") from e
    if not fecha_dolar or fecha_dolar != fecha_euro:
        raise FuenteCaida(f"dolarapi trae el dólar del «{fecha_dolar}» y el euro del «{fecha_euro}»")
    return {
        "ves_por_usd": _texto(_cifra(dolar["promedio"])),
        "ves_por_eur": _texto(_cifra(euro["promedio"])),
        "fecha_valor": fecha_dolar,
        "fuente": EL_RESPALDO,
    }


def bcv_desde_dolarapi() -> dict:
    """El respaldo, sólo si la página del BCV no contesta.

    **dolarapi llega tarde, y por eso no es la fuente principal.** Cambia a la
    tasa nueva a la medianoche de su fecha valor, no cuando el BCV la publica a
    las 4:30 de la tarde: medido en septiembre de 2026, cada tasa nueva aparecía
    a las 5:23 de la mañana de su fecha valor. Con un fin de semana o un feriado
    de por medio, días.
    """
    return leer_dolarapi(_json(_pedir("https://ve.dolarapi.com/v1/dolares/oficial")),
                         _json(_pedir("https://ve.dolarapi.com/v1/euros")))


# **Cuándo se mira el BCV.** Antonio, el 2026-10-25: el BCV publica hacia las
# 4:30 de la tarde, a veces antes y a veces hacia las 5, y lo que publica rige
# desde ese momento hasta la publicación siguiente; la del viernes cubre el fin
# de semana y el lunes, y un feriado no publica. Y: «Vamos a consultar la tasa
# BCB cada media hora después de las 4 de la tarde».
#
# Se empieza a las 3:30 y no a las 4 por lo que él mismo advirtió: el horario a
# veces se adelanta. Con la primera pasada a las 3:47, una publicación temprana
# no se recoge con una hora de retraso.
EMPIEZA_LA_TARDE = (15, 30)

# **El vistazo de la noche.** Ya vista la publicación de la tarde, una mirada
# más después de las 10, por si el BCV la corrigió. Sin ella, una corrección
# de la tarde no se vería hasta la mañana siguiente.
VISTAZO_DE_LA_NOCHE = 22

# **El vistazo de la mañana.** Una sola mirada entre las 7 y las 10, por si el
# BCV publicó de madrugada o una pasada de la tarde no llegó.
VISTAZO_DE_LA_MANANA = range(7, 10)


# **Las dos monedas del BCV**: cómo se llama cada una en lo que se lee de la página o de dolarapi, y su bloque y su
# cifra en lo que se publica. Cada una lleva su propio «desde cuándo»: el BCV a veces corrige sólo una.
MONEDAS_DEL_BCV = {
    "usd": {"leida": "ves_por_usd", "bloque": "ves_por_usd_bcv", "cifra": "ves_por_usd"},
    "eur": {"leida": "ves_por_eur", "bloque": "ves_por_eur_bcv", "cifra": "valor"},
}


def toca_mirar_bcv(anterior: dict, ahora: datetime) -> bool:
    """Si en esta pasada toca mirar la página del BCV.

    - **Desde las 3:30 de la tarde, en cada pasada**, hasta que **la página**
      enseña algo nuevo (una publicación o una corrección). Que lo diera
      dolarapi no cuenta: llega tarde y no dice cuándo publicó el BCV, así que
      se sigue mirando la página. Los días sin publicación —fines de semana y
      feriados— se mira hasta medianoche sin encontrar nada, y no pasa nada: la
      última sigue rigiendo.
    - **Una vez más por la noche**, ya vista la de la tarde, por si la corrigió.
    - **Una vez por la mañana**, entre las 7 y las 10.
    - **Siempre, si nunca se ha leído la página.**

    `consultado` sólo lo mueve una lectura de la página, así que si la página
    falla, la pasada siguiente vuelve a intentarlo.
    """
    caracas = ahora.astimezone(CARACAS)
    consultado = _momento(anterior.get("consultado"))
    if consultado is None:
        return True
    hoy = caracas.replace(minute=0, second=0, microsecond=0)
    tarde = hoy.replace(hour=EMPIEZA_LA_TARDE[0], minute=EMPIEZA_LA_TARDE[1])
    if caracas >= tarde:
        ya_la_dio_la_pagina = False
        for moneda in MONEDAS_DEL_BCV:
            estado = anterior.get(moneda) or {}
            visto = _momento(estado.get("publicado_visto"))
            if estado.get("visto_por") == LA_PAGINA and visto is not None and visto >= tarde:
                ya_la_dio_la_pagina = True
        if not ya_la_dio_la_pagina:
            return True
        noche = hoy.replace(hour=VISTAZO_DE_LA_NOCHE)
        return caracas >= noche and consultado < noche
    if caracas.hour in VISTAZO_DE_LA_MANANA:
        return consultado < hoy.replace(hour=0)
    return False


def anotar_bcv(leido: dict, anterior: dict, ahora: datetime) -> dict | None:
    """La publicación del BCV, con desde cuándo rige cada moneda. `None` si no trae nada nuevo que valga.

    **Una lectura de la página manda.** Si trae algo nuevo para una moneda
    —cambia la fecha valor o su cifra, porque el BCV a veces corrige—, se
    apunta **para esa moneda**:

    - `publicado_visto`: este momento, **desde cuándo rige** con la regla de
      Antonio;
    - `no_estaba_a_las`: la última vez que la página enseñaba la de antes. Entre
      las dos queda acotado cuándo publicó el BCV: media hora como mucho si
      GitHub corre a su hora, y si una pasada se retrasó o la página estuvo
      caída, el hueco se ve;
    - `visto_por`: quién la vio primero;
    - `obtenido`: el momento de la lectura que trajo esa cifra.

    **Cada moneda, lo suyo.** Si el BCV corrige sólo el euro, el dólar conserva
    sus cuatro marcas: decir que el dólar «no estaba» a una hora en que ya
    estaba es falso, y quien lo lee movería desde cuándo rige.

    Si una moneda no trae nada nuevo, conserva sus marcas, y sólo se apunta que
    se volvió a mirar (`consultado`).

    **Una lectura de dolarapi sólo cuenta si trae una publicación de fecha
    posterior a la que ya se tenía.** Con la misma fecha no trae nada: o es la
    misma, o es una versión sin la corrección que la página ya dio. Y como llega
    tarde, una publicación que dio dolarapi lleva `respaldo` hasta la siguiente:
    su `publicado_visto` es cuándo la vio dolarapi, no cuándo publicó el BCV.

    **Una fecha valor anterior a la que ya se tenía no es una publicación: es
    una fuente atrasada**, y se rechaza.
    """
    momento = _ahora_texto(ahora)
    de_la_pagina = leido.get("fuente") == LA_PAGINA
    fecha = leido.get("fecha_valor")
    if not fecha:
        raise FuenteCaida(f"{leido.get('fuente')} no dice la fecha valor")
    fechas_de_antes = [(anterior.get(m) or {}).get("fecha_valor") for m in MONEDAS_DEL_BCV]
    antes = max((f for f in fechas_de_antes if f), default=None)
    if antes and fecha < antes:
        raise FuenteCaida(f"{leido.get('fuente')} trae la publicación del {fecha}, anterior a la del {antes} que ya se tenía")
    if not de_la_pagina and antes and fecha <= antes:
        return None
    salida: dict = {
        "fecha_valor": fecha,
        "fuente": leido["fuente"],
        "consultado": momento if de_la_pagina else anterior.get("consultado"),
    }
    for moneda, nombres in MONEDAS_DEL_BCV.items():
        previa = anterior.get(moneda) or {}
        cifra = leido[nombres["leida"]]
        if fecha != previa.get("fecha_valor") or cifra != previa.get("cifra"):
            salida[moneda] = {
                "cifra": cifra,
                "fecha_valor": fecha,
                "publicado_visto": momento,
                "no_estaba_a_las": anterior.get("consultado"),
                "visto_por": leido["fuente"],
                "obtenido": momento,
            }
        else:
            salida[moneda] = {**previa, "cifra": cifra, "fecha_valor": fecha}
    return salida


def bloques_del_bcv(bcv: dict) -> dict:
    """Las dos claves de siempre, con lo de antes y lo nuevo.

    `ves_por_usd_bcv` y `ves_por_eur_bcv` conservan **todos los campos que ya
    tenían** y con el mismo significado, porque la app anterior los lee
    (`ves_por_usd`, `valor`, `fuente`, `fecha_valor`, `contrastada`; `obtenido`
    lo escribe pero ya no lo lee nadie). Lo nuevo se añade al lado:
    `publicado_visto`, `no_estaba_a_las`, `visto_por`, `consultado` y
    `respaldo`, **cada bloque con los de su moneda**.
    """
    def bloque(moneda: str) -> dict:
        estado = bcv.get(moneda) or {}
        return {
            "fuente": bcv["fuente"],
            "fecha_valor": estado.get("fecha_valor"),
            "obtenido": estado.get("obtenido"),
            "consultado": bcv.get("consultado"),
            "publicado_visto": estado.get("publicado_visto"),
            "no_estaba_a_las": estado.get("no_estaba_a_las"),
            "visto_por": estado.get("visto_por"),
            "respaldo": estado.get("visto_por") != LA_PAGINA,
        }

    return {
        # `contrastada` era la comparación entre dolarapi y la página del BCV.
        # Ahora la fuente es la página misma: no hay nada que contrastar, y se
        # deja vacío en vez de afirmar un contraste que no se hizo.
        "ves_por_usd_bcv": {"ves_por_usd": bcv["usd"]["cifra"], **bloque("usd"), "contrastada": None},
        "ves_por_eur_bcv": {"valor": bcv["eur"]["cifra"], **bloque("eur")},
    }


def bcv_anterior(anterior: dict) -> dict:
    """Lo último que se sabía del BCV, en la forma de trabajo de aquí: lo común y cada moneda con lo suyo.

    Si lo anterior lo escribió la versión vieja de este registrador —sin
    `consultado`—, sale sin esa marca, y entonces la primera pasada mira la
    página y empieza a contar desde ahí. Si lo escribió la versión de antes de
    separar las monedas, cada bloque ya trae sus marcas y se leen igual.
    """
    salida: dict = {
        "fecha_valor": (anterior.get("ves_por_usd_bcv") or {}).get("fecha_valor"),
        "fuente": (anterior.get("ves_por_usd_bcv") or {}).get("fuente"),
        "consultado": (anterior.get("ves_por_usd_bcv") or {}).get("consultado"),
    }
    for moneda, nombres in MONEDAS_DEL_BCV.items():
        bloque = anterior.get(nombres["bloque"]) or {}
        salida[moneda] = {
            "cifra": bloque.get(nombres["cifra"]),
            "fecha_valor": bloque.get("fecha_valor"),
            "publicado_visto": bloque.get("publicado_visto"),
            "no_estaba_a_las": bloque.get("no_estaba_a_las"),
            "visto_por": bloque.get("visto_por"),
            "obtenido": bloque.get("obtenido"),
        }
    return salida


# ---------------------------------------------------------------------------
# TASA DE MERCADO (Binance P2P)
# ---------------------------------------------------------------------------

BINANCE = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"

# **Cuánto vale una operación normal**, en dólares. Sólo cuentan los anuncios
# que la aceptan: medido el 2026-10-25, sin ese filtro el primer anuncio de un
# lado estaba a 980,54 con un límite de 300 a 400 bolívares, y los primeros del
# otro eran de comerciantes que pedían mínimos de tres millones. Ninguno de los
# dos es el precio al que la gente cambia. Con el filtro, la mediana de la
# venta salió 1.003,05, y el paralelo que publica dolarapi, 1.002,95.
OPERACION_NORMAL_EN_DOLARES = Decimal(100)
ANUNCIOS = 10
MINIMO_DE_ANUNCIOS = 5

# Qué lado es qué, porque en esta API es fácil confundirse: `tradeType` es lo
# que hace **quien consulta**. "SELL" trae los anuncios de quien compra USDT:
# es lo que te dan por vender uno. "BUY" trae los de quien vende: lo que
# cuesta comprarlo. Comprobado el 2026-10-25 leyendo el `tradeType` de cada
# anuncio, que es el del anunciante y sale al revés.
VENDER_USDT = "SELL"
COMPRAR_USDT = "BUY"


def precios_de_binance(crudo) -> list[Decimal]:
    try:
        return [_cifra(a["adv"]["price"]) for a in (crudo.get("data") or []) if (a.get("adv") or {}).get("price")]
    except (AttributeError, TypeError, KeyError) as e:
        raise FuenteCaida(f"Binance contestó con otra forma: {e}") from e


def resumen_de_binance(precios: list[Decimal]) -> dict:
    """La mediana de los anuncios, y lo que hace falta para fiarse de ella.

    **La mediana y no el promedio**: un anuncio raro que se cuele arriba no la
    mueve. Antes se descartaba el primero y se promediaban los cinco
    siguientes; eso protegía de uno raro, pero no de dos.
    """
    if len(precios) < MINIMO_DE_ANUNCIOS:
        raise FuenteCaida(f"Binance sólo devolvió {len(precios)} anuncios")
    mediana = statistics.median(precios)
    return {
        "ves_por_usdt": _texto(mediana),
        "muestras": len(precios),
        "minimo": _texto(min(precios)),
        "maximo": _texto(max(precios)),
        "dispersion_pct": _redondeada((max(precios) - min(precios)) / mediana * 100, 4),
    }


def un_lado_de_binance(lado: str, monto_bs: Decimal | None) -> dict:
    cuerpo = {"page": 1, "rows": ANUNCIOS, "asset": "USDT", "tradeType": lado, "fiat": "VES", "payTypes": []}
    if monto_bs is not None:
        cuerpo["transAmount"] = str(monto_bs)
    return resumen_de_binance(precios_de_binance(_json(_pedir(BINANCE, metodo="POST", cuerpo=cuerpo))))


def monto_de_una_operacion_normal(anterior: dict) -> Decimal | None:
    """Cien dólares en bolívares, con la última tasa de mercado conocida.

    Se calcula cada vez porque el bolívar se mueve: una cifra fija en bolívares
    dejaría de ser «una operación normal» en unos meses. Sin tasa anterior —la
    primera pasada de todas— no se filtra, y se dice.
    """
    tasa = (anterior.get("ves_por_usdt_mercado") or {}).get("ves_por_usdt")
    if not tasa:
        return None
    try:
        return (OPERACION_NORMAL_EN_DOLARES * _cifra(tasa)).quantize(Decimal(1))
    except FuenteCaida:
        return None


def mercado_desde_binance(anterior: dict) -> dict:
    """El USDT contra el bolívar, por los dos lados.

    **La tasa de mercado es lo que te dan por vender un USDT**: Antonio, en
    agosto, «la tasa paralela es el precio de venta de USDT en Binance». Se
    guarda además lo que cuesta comprarlo, para que se sepa cuánto hay entre
    una cosa y la otra. Si ese lado falla, la venta se publica igual.
    """
    monto = monto_de_una_operacion_normal(anterior)
    venta = un_lado_de_binance(VENDER_USDT, monto)
    salida = {
        **venta,
        "fuente": "binance-p2p",
        "metodo": (
            f"mediana de los {ANUNCIOS} primeros anuncios que aceptan "
            f"{OPERACION_NORMAL_EN_DOLARES} dólares en bolívares"
            if monto is not None else
            f"mediana de los {ANUNCIOS} primeros anuncios, sin filtro de monto"
        ),
        "monto_bs": str(monto) if monto is not None else None,
    }
    try:
        salida["compra"] = un_lado_de_binance(COMPRAR_USDT, monto)
    except FuenteCaida as e:
        salida["compra"] = None
        salida["fallo_compra"] = str(e)
    return salida


# ---------------------------------------------------------------------------
# DIVISAS INTERNACIONALES Y CRIPTOMONEDAS
# ---------------------------------------------------------------------------

# frankfurter se mudó de `api.frankfurter.app` a `api.frankfurter.dev/v1` y la
# dirección vieja contesta con una redirección. Se pide la nueva directamente.
FRANKFURTER = "https://api.frankfurter.dev/v1/latest?base=USD&symbols=EUR,BRL,MXN,CAD,GBP,CHF,JPY"

# El Banco Central Europeo publica una vez por día hábil. Una vez que se tiene
# el dato de hoy no se pregunta más; si no, como mucho cada dos horas.
CADA_CUANTO_LAS_INTERNACIONALES = timedelta(hours=2)


def internacionales() -> dict:
    """Lo estándar, del Banco Central Europeo. Sin clave y sin exagerar.

    Sólo se piden las que el BCE publica de verdad: de LatAm sólo tiene el real
    brasileño y el peso mexicano. Pedir peso colombiano o argentino no da
    error, simplemente no vienen — y una clave que nunca llega es una clave que
    alguien acabará interpretando como cero.
    """
    crudo = _json(_pedir(FRANKFURTER))
    try:
        tasas = crudo.get("rates") or {}
        fecha = crudo.get("date")
        por_usd = {k: _texto(_cifra(v)) for k, v in tasas.items()}
    except (AttributeError, TypeError) as e:
        raise FuenteCaida(f"frankfurter contestó con otra forma: {e}") from e
    if not por_usd:
        raise FuenteCaida("frankfurter no trajo ninguna tasa")
    return {"por_usd": por_usd, "fuente": "frankfurter-bce", "fecha_valor": fecha}


def toca_mirar_internacionales(previas: dict, ahora: datetime) -> bool:
    if not previas:
        return True
    if previas.get("fecha_valor") == ahora.astimezone(CARACAS).date().isoformat():
        return False
    consultado = _momento(previas.get("consultado") or previas.get("obtenido"))
    return consultado is None or ahora - consultado >= CADA_CUANTO_LAS_INTERNACIONALES


def criptomonedas() -> dict:
    """Bitcoin y USDT contra el dólar.

    USDT vale casi exactamente un dólar, pero *casi* no es *exactamente*: si se
    da por supuesto que vale 1, cada operación en USDT arrastra un error
    pequeño que se acumula. Se pregunta y se guarda como cualquier otra tasa.

    Dos formas, y las dos exactas: `usd_por` es el precio tal cual lo da la
    fuente (un bitcoin, tantos dólares), y `por_usd` es la de siempre —cuántas
    unidades hacen un dólar—, que lee la app anterior, con doce decimales.
    """
    crudo = _json(_pedir(
        "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,tether&vs_currencies=usd"
    ))
    usd_por = {}
    try:
        for ident, codigo in (("bitcoin", "BTC"), ("tether", "USDT")):
            precio = (crudo.get(ident) or {}).get("usd")
            if precio is not None:
                usd_por[codigo] = _cifra(precio)
    except (AttributeError, TypeError) as e:
        raise FuenteCaida(f"coingecko contestó con otra forma: {e}") from e
    if not usd_por:
        raise FuenteCaida("coingecko no trajo ningún precio")
    with localcontext() as ctx:
        ctx.prec = 40
        por_usd = {k: _redondeada(Decimal(1) / v, 12) for k, v in usd_por.items()}
    return {"usd_por": {k: str(v) for k, v in usd_por.items()}, "por_usd": por_usd, "fuente": "coingecko"}


# ---------------------------------------------------------------------------
# EL TRABAJO
# ---------------------------------------------------------------------------


def cargar_anterior() -> dict:
    if not ULTIMAS.exists():
        return {}
    try:
        datos = json.loads(ULTIMAS.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return datos if isinstance(datos, dict) else {}


def _intentar(fallos: list[str], nombre: str, trabajo):
    """Hace un trabajo de una fuente sin que su fallo tumbe la pasada.

    Lo esperado (`FuenteCaida`) y lo inesperado se apuntan igual en `fallos`:
    una fuente que contesta algo raro no puede llevarse por delante lo que sí
    trajeron las demás.
    """
    try:
        return trabajo()
    except FuenteCaida as e:
        fallos.append(f"{nombre}: {e}")
    except Exception as e:  # noqa: BLE001 — cualquier sorpresa de una fuente se apunta, no tumba la pasada
        fallos.append(f"{nombre}: {type(e).__name__}: {e}")
    return None


def registrar(anterior: dict, ahora: datetime) -> dict:
    """Una pasada: lo que toca consultar, y lo de antes para lo que falló.

    Ninguna fuente caída borra lo que se sabía: se repite su bloque anterior
    **con su hora de entonces**, así que quien lo lea sabe cuánto tiene de
    viejo. Lo que falló se apunta en `fallos`.
    """
    global _LIMITE
    _LIMITE = time.monotonic() + DURACION_MAXIMA
    momento = _ahora_texto(ahora)
    salida: dict = {"actualizado": momento}
    fallos: list[str] = []

    # --- Mercado: siempre, porque cambia a cada minuto ---------------------
    mercado = _intentar(fallos, "mercado", lambda: mercado_desde_binance(anterior))
    if mercado:
        salida["ves_por_usdt_mercado"] = mercado | {"obtenido": momento}
    elif anterior.get("ves_por_usdt_mercado"):
        salida["ves_por_usdt_mercado"] = anterior["ves_por_usdt_mercado"]

    # --- Oficial: dólar y euro, cuando toca --------------------------------
    antes = bcv_anterior(anterior)
    bcv = None
    if toca_mirar_bcv(antes, ahora):
        leido = _intentar(fallos, "bcv", bcv_desde_la_pagina)
        if leido is None:
            leido = _intentar(fallos, "bcv-respaldo", bcv_desde_dolarapi)
        if leido is not None:
            bcv = _intentar(fallos, "bcv", lambda: anotar_bcv(leido, antes, ahora))
    if bcv:
        salida.update(bloques_del_bcv(bcv))
    else:
        for clave in ("ves_por_usd_bcv", "ves_por_eur_bcv"):
            if anterior.get(clave):
                salida[clave] = anterior[clave]

    # --- Internacionales: cuando hay dato nuevo ----------------------------
    previas = anterior.get("internacionales") or {}
    inter = None
    if toca_mirar_internacionales(previas, ahora):
        inter = _intentar(fallos, "internacionales", internacionales)
    if inter:
        salida["internacionales"] = inter | {"obtenido": momento, "consultado": momento}
    elif previas:
        salida["internacionales"] = previas

    # --- Cripto: cada pasada, el bitcoin se mueve ---------------------------
    cripto = _intentar(fallos, "cripto", criptomonedas)
    if cripto:
        salida["criptomonedas"] = cripto | {"obtenido": momento}
    elif anterior.get("criptomonedas"):
        salida["criptomonedas"] = anterior["criptomonedas"]

    if fallos:
        salida["fallos"] = fallos
    return salida


def main() -> int:
    ahora = datetime.now(timezone.utc)
    salida = registrar(cargar_anterior(), ahora)

    ULTIMAS.write_text(json.dumps(salida, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # El histórico se añade siempre: es la única memoria que va a existir de
    # a cuánto estaba el bolívar cada media hora.
    HISTORICO.mkdir(exist_ok=True)
    mes = HISTORICO / f"{ahora.astimezone(CARACAS):%Y-%m}.jsonl"
    with mes.open("a", encoding="utf-8") as f:
        f.write(json.dumps(salida, ensure_ascii=False) + "\n")

    print(json.dumps(salida, ensure_ascii=False, indent=2))

    # **No se sale con error, y no es dejadez: es dónde va la alarma.**
    #
    # Antes se devolvía 1 cuando ninguna fuente respondía, para que GitHub
    # mandara un correo. El correo acabó llegando por lo que no era: GitHub se
    # queda sin máquinas libres, el trabajo ni siquiera arranca, y de todas
    # formas manda el aviso. Muchos correos por algo que se arregla solo enseñan
    # a no leerlos, y entonces el día que llegue el bueno tampoco se lee.
    #
    # La alarma vive **donde se miran las cifras**: la app sabe de cuándo es cada
    # tasa y lo dice en cuanto se queda vieja, venga el retraso de donde venga.
    # Aquí sólo se deja constancia en el propio archivo, en `fallos`.
    if "ves_por_usdt_mercado" not in salida and "ves_por_usd_bcv" not in salida:
        print("NINGUNA fuente respondió", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
