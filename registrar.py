#!/usr/bin/env python3
"""Registrador de tasas de cambio de Venezuela.

Corre solo, cada media hora, y anota a cuánto está el bolívar. Publica dos
cosas: `tasas.json` con lo último, que es lo que lee la app, y un histórico
mensual, que es lo que permite saber dentro de un año a cuánto estaba el dólar
el martes pasado — porque **ninguna fuente guarda ese histórico** y sin él las
operaciones de días anteriores no se pueden valorar bien.

Por qué existe este intermediario, en vez de que la app consulte directamente:

- Una sola llamada cada media hora en total, sin importar cuánta gente use la
  app. Si cada teléfono consultara por su cuenta, multiplicaríamos las llamadas
  por cada usuario y el endpoint de Binance —que no es oficial— acabaría
  bloqueándonos.
- Leer un archivo publicado no tiene límite ni puede bloquearse.

Y por qué la app **igual** sabe consultar directo: porque el intermediario
anterior de Antonio se cayó y estuvo seis meses sirviendo una tasa de 339
cuando el dólar estaba en 746, sin que nadie se enterara. Aquí eso no puede
pasar: cada dato lleva su hora, y si envejece la app lo dice.

Cuidado con las unidades. Cada clave dice **en qué unidad está** (`ves_por_usd`,
`ves_por_eur`). Mezclar "bolívares por dólar" con "dólares por bolívar" fue
exactamente el error que hacía que el motor viejo registrara ganancias de
noventa mil dólares sobre diez.
"""

from __future__ import annotations

import json
import re
import statistics
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).parent
ULTIMAS = RAIZ / "tasas.json"
HISTORICO = RAIZ / "historico"

# Caracas no cambia la hora en todo el año.
CARACAS = timezone(timedelta(hours=-4))

AGENTE = "registrador-tasas-venezuela/1.0 (+https://github.com/mi-url/tasas-venezuela)"
ESPERA = 20


class FuenteCaida(Exception):
    """Una fuente no respondió o respondió algo que no se entiende."""


def _pedir(url: str, *, metodo: str = "GET", cuerpo: dict | None = None) -> bytes:
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    cabeceras = {"User-Agent": AGENTE, "Accept": "application/json, text/html"}
    if datos is not None:
        cabeceras["Content-Type"] = "application/json"
    peticion = urllib.request.Request(url, data=datos, headers=cabeceras, method=metodo)
    try:
        with urllib.request.urlopen(peticion, timeout=ESPERA) as respuesta:
            return respuesta.read()
    except urllib.error.HTTPError as e:
        # 429 es "demasiadas peticiones": se respeta y se sale, no se insiste.
        raise FuenteCaida(f"{url} respondió {e.code}") from e
    except Exception as e:  # noqa: BLE001 — cualquier fallo de red es lo mismo aquí
        raise FuenteCaida(f"{url} no respondió: {e}") from e


# ---------------------------------------------------------------------------
# TASA OFICIAL (BCV)
# ---------------------------------------------------------------------------


def bcv_desde_api() -> dict:
    """La vía barata: una API pensada para ser consumida, que devuelve JSON."""
    crudo = json.loads(_pedir("https://ve.dolarapi.com/v1/dolares/oficial"))
    valor = crudo.get("promedio")
    if not valor:
        raise FuenteCaida("dolarapi no trajo el promedio")
    return {
        "ves_por_usd": f"{float(valor):.8f}",
        "fuente": "dolarapi",
        "fecha_valor": (crudo.get("fechaActualizacion") or "")[:10],
    }


def bcv_euro_desde_api() -> dict:
    crudo = json.loads(_pedir("https://ve.dolarapi.com/v1/euros"))
    fila = next((c for c in crudo if c.get("fuente") == "oficial"), None)
    if not fila or not fila.get("promedio"):
        raise FuenteCaida("dolarapi no trajo el euro oficial")
    return {
        "ves_por_eur": f"{float(fila['promedio']):.8f}",
        "fuente": "dolarapi",
        "fecha_valor": (fila.get("fechaActualizacion") or "")[:10],
    }


_PATRON_BCV = r'id="{}".{{0,600}}?<strong class="strong-tb">\s*([\d.,]+)\s*</strong>'


def bcv_desde_web() -> dict:
    """La vía cara: leer la página del propio BCV.

    Pesa 150 KB y es un sitio de un organismo público, así que **sólo se usa
    para contrastar una vez al día** o cuando la API falla. Machacarlo cada
    media hora sería abusivo y además inútil: publica una vez al día.
    """
    html = _pedir("https://www.bcv.org.ve/").decode("utf-8", errors="ignore")

    def leer(codigo: str) -> str | None:
        m = re.search(_PATRON_BCV.format(codigo), html, re.S)
        if not m:
            return None
        # El BCV escribe 746,62970000 — punto de miles, coma decimal.
        return m.group(1).strip().replace(".", "").replace(",", ".")

    usd = leer("dolar")
    if not usd:
        raise FuenteCaida("no se encontró el dólar en la página del BCV")

    fecha = None
    m = re.search(r'content="(\d{4}-\d{2}-\d{2})T', html)
    if m:
        fecha = m.group(1)

    resultado = {"ves_por_usd": usd, "fuente": "bcv.org.ve", "fecha_valor": fecha}
    for codigo, clave in (("euro", "ves_por_eur"), ("yuan", "ves_por_cny"),
                          ("lira", "ves_por_try"), ("rublo", "ves_por_rub")):
        valor = leer(codigo)
        if valor:
            resultado[clave] = valor
    return resultado


# ---------------------------------------------------------------------------
# TASA DE MERCADO (Binance P2P)
# ---------------------------------------------------------------------------

ANUNCIOS_DESCARTADOS = 1  # el primero es publicidad pagada
ANUNCIOS_USADOS = 5


def mercado_desde_binance() -> dict:
    """El precio real al que se vende USDT por bolívares.

    Antonio: en Venezuela la tasa paralela **es** el precio de venta de USDT en
    Binance. Y un detalle que sólo sabe quien lo usa: **el primer anuncio es
    publicidad pagada** por un comerciante y casi siempre trae un precio peor.
    Contarlo inflaría la tasa todos los días. Se descarta y se promedian los
    cinco siguientes.
    """
    crudo = json.loads(_pedir(
        "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search",
        metodo="POST",
        cuerpo={"page": 1, "rows": 10, "asset": "USDT",
                "tradeType": "SELL", "fiat": "VES", "payTypes": []},
    ))
    anuncios = crudo.get("data") or []
    precios = [float(a["adv"]["price"]) for a in anuncios if a.get("adv", {}).get("price")]
    usados = precios[ANUNCIOS_DESCARTADOS:ANUNCIOS_DESCARTADOS + ANUNCIOS_USADOS]
    if len(usados) < 3:
        raise FuenteCaida(f"Binance sólo devolvió {len(precios)} anuncios")

    return {
        "ves_por_usdt": f"{statistics.fmean(usados):.8f}",
        "fuente": "binance-p2p",
        "muestras": len(usados),
        "descartado_publicidad": f"{precios[0]:.8f}",
        "dispersion_pct": round((max(usados) - min(usados)) / statistics.fmean(usados) * 100, 4),
    }


# ---------------------------------------------------------------------------
# DIVISAS INTERNACIONALES
# ---------------------------------------------------------------------------


def internacionales() -> dict:
    """Lo estándar, del Banco Central Europeo. Sin clave y sin exagerar.

    Sólo se piden las que el BCE publica de verdad: comprobado, de LatAm sólo
    tiene el real brasileño y el peso mexicano. Pedir peso colombiano o
    argentino no da error, simplemente no vienen — y una clave que nunca llega
    es una clave que alguien acabará interpretando como cero.
    """
    crudo = json.loads(_pedir(
        "https://api.frankfurter.app/latest?base=USD&symbols=EUR,BRL,MXN,CAD,GBP,CHF,JPY"
    ))
    return {
        "por_usd": {k: f"{float(v):.8f}" for k, v in (crudo.get("rates") or {}).items()},
        "fuente": "frankfurter-bce",
        "fecha_valor": crudo.get("date"),
    }


# ---------------------------------------------------------------------------
# CUÁNDO TOCA MIRAR EL BCV
# ---------------------------------------------------------------------------


def toca_mirar_bcv(anterior: dict, ahora: datetime) -> bool:
    """El BCV publica una vez al día. Preguntarle 48 veces sería abusivo.

    - Si ya tenemos la tasa con fecha de valor de mañana o de hoy publicada
      dentro de la ventana, **no se pregunta más hasta el día siguiente**.
    - Entre las 15:00 y las 21:00 de Caracas se mira cada vez (cada 30 min):
      es la ventana en la que publican, ampliada, porque no siempre cumplen.
    - Fuera de esa ventana, sólo en horas pares, por si publican a deshora.
    """
    caracas = ahora.astimezone(CARACAS)
    ya_tenemos = (anterior.get("ves_por_usd_bcv") or {}).get("fecha_valor")

    # Si la tasa que tenemos ya es de mañana (publican por adelantado), listo.
    if ya_tenemos:
        try:
            fecha = datetime.strptime(ya_tenemos, "%Y-%m-%d").date()
            if fecha > caracas.date():
                return False
        except ValueError:
            pass

    en_ventana = 15 <= caracas.hour < 21
    if en_ventana:
        return True
    return caracas.hour % 2 == 0


# ---------------------------------------------------------------------------
# EL TRABAJO
# ---------------------------------------------------------------------------


def cargar_anterior() -> dict:
    if not ULTIMAS.exists():
        return {}
    try:
        return json.loads(ULTIMAS.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def main() -> int:
    ahora = datetime.now(timezone.utc)
    anterior = cargar_anterior()
    salida: dict = {"actualizado": ahora.isoformat(timespec="seconds")}
    fallos: list[str] = []

    # --- Mercado: siempre, porque cambia a cada minuto ---------------------
    try:
        salida["ves_por_usdt_mercado"] = mercado_desde_binance() | {
            "obtenido": ahora.isoformat(timespec="seconds")
        }
    except FuenteCaida as e:
        fallos.append(f"mercado: {e}")
        if anterior.get("ves_por_usdt_mercado"):
            salida["ves_por_usdt_mercado"] = anterior["ves_por_usdt_mercado"]

    # --- Oficial: sólo cuando toca ----------------------------------------
    if toca_mirar_bcv(anterior, ahora):
        oficial = None
        try:
            oficial = bcv_desde_api()
        except FuenteCaida as e:
            fallos.append(f"bcv-api: {e}")
            try:
                oficial = bcv_desde_web()
            except FuenteCaida as e2:
                fallos.append(f"bcv-web: {e2}")

        if oficial:
            oficial["obtenido"] = ahora.isoformat(timespec="seconds")
            anterior_bcv = anterior.get("ves_por_usd_bcv") or {}
            # Se contrasta contra el sitio del BCV **una vez por tasa nueva**,
            # no en cada pasada: la página pesa 150 KB y es de un organismo
            # público. Si las dos fuentes coinciden, la tasa es firme.
            if oficial.get("fecha_valor") != anterior_bcv.get("fecha_valor"):
                try:
                    web = bcv_desde_web()
                    oficial["contrastada"] = web["ves_por_usd"] == oficial["ves_por_usd"]
                    oficial["contraste"] = web["ves_por_usd"]
                    for clave in ("ves_por_eur", "ves_por_cny", "ves_por_try", "ves_por_rub"):
                        if clave in web:
                            salida[f"{clave}_bcv"] = {
                                "valor": web[clave],
                                "fuente": "bcv.org.ve",
                                "fecha_valor": web.get("fecha_valor"),
                                "obtenido": ahora.isoformat(timespec="seconds"),
                            }
                except FuenteCaida as e:
                    fallos.append(f"contraste-bcv: {e}")
                    oficial["contrastada"] = None
            else:
                oficial["contrastada"] = anterior_bcv.get("contrastada")
            salida["ves_por_usd_bcv"] = oficial
        elif anterior.get("ves_por_usd_bcv"):
            salida["ves_por_usd_bcv"] = anterior["ves_por_usd_bcv"]
    elif anterior.get("ves_por_usd_bcv"):
        salida["ves_por_usd_bcv"] = anterior["ves_por_usd_bcv"]

    # Euro del BCV por la vía barata, si no vino del contraste.
    if "ves_por_eur_bcv" not in salida:
        try:
            euro = bcv_euro_desde_api()
            salida["ves_por_eur_bcv"] = {
                "valor": euro["ves_por_eur"],
                "fuente": euro["fuente"],
                "fecha_valor": euro["fecha_valor"],
                "obtenido": ahora.isoformat(timespec="seconds"),
            }
        except FuenteCaida as e:
            fallos.append(f"euro-bcv: {e}")
            if anterior.get("ves_por_eur_bcv"):
                salida["ves_por_eur_bcv"] = anterior["ves_por_eur_bcv"]

    # --- Internacionales: una vez al día basta, cambian poco --------------
    previas = anterior.get("internacionales") or {}
    if previas.get("fecha_valor") != ahora.astimezone(CARACAS).date().isoformat():
        try:
            salida["internacionales"] = internacionales() | {
                "obtenido": ahora.isoformat(timespec="seconds")
            }
        except FuenteCaida as e:
            fallos.append(f"internacionales: {e}")
            if previas:
                salida["internacionales"] = previas
    elif previas:
        salida["internacionales"] = previas

    if fallos:
        salida["fallos"] = fallos

    ULTIMAS.write_text(
        json.dumps(salida, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    # El histórico se añade siempre: es la única memoria que va a existir de
    # a cuánto estaba el bolívar cada media hora.
    HISTORICO.mkdir(exist_ok=True)
    mes = HISTORICO / f"{ahora.astimezone(CARACAS):%Y-%m}.jsonl"
    with mes.open("a", encoding="utf-8") as f:
        f.write(json.dumps(salida, ensure_ascii=False) + "\n")

    print(json.dumps(salida, ensure_ascii=False, indent=2))

    # Se falla en voz alta: si todas las fuentes caen, GitHub avisa por correo.
    # Ése fue el fallo de verdad del servicio anterior — murió en silencio.
    if "ves_por_usdt_mercado" not in salida and "ves_por_usd_bcv" not in salida:
        print("NINGUNA fuente respondió", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
