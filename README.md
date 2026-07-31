# Tasas de cambio de Venezuela

Registro público y automático de a cuánto está el bolívar. Se actualiza solo cada media hora y guarda
el histórico, que es lo que ninguna fuente pública ofrece.

**Lo último está en [`tasas.json`](tasas.json).** El histórico, en [`historico/`](historico), un archivo
por mes con una línea por consulta.

## Qué publica

| Clave | Qué es | De dónde sale |
|---|---|---|
| `ves_por_usd_bcv` | La tasa oficial del Banco Central | `ve.dolarapi.com`, contrastada contra `bcv.org.ve` |
| `ves_por_usdt_mercado` | La tasa de la calle: el precio real de venta de USDT | Binance P2P |
| `ves_por_eur_bcv` | El euro oficial, que muchos comercios usan | igual que el dólar |
| `ves_por_cny_bcv`, `..._try_bcv`, `..._rub_bcv` | Yuan, lira y rublo oficiales | `bcv.org.ve` |
| `internacionales` | Divisas estándar contra el dólar | Banco Central Europeo, vía `frankfurter.app` |

**Cada clave dice en qué unidad está.** `ves_por_usd` son bolívares por un dólar, no al revés. Puede
parecer pedante hasta que se mezclan las dos: confundirlas es lo que hace que un sistema registre una
ganancia de noventa mil dólares sobre diez.

Y cada dato viene con **de dónde salió y a qué hora**. Una tasa sin fecha es una tasa en la que no se
puede confiar.

## Dos decisiones que no son obvias

**El primer anuncio de Binance se descarta.** Es publicidad que paga un comerciante para salir arriba, y
casi siempre trae peor precio. Contarlo inflaría la tasa alrededor de un 0,4% todos los días. Se usa el
promedio de los cinco siguientes.

**Al BCV no se le pregunta cada media hora.** Publica una vez al día, entre las 4 y las 6 de la tarde de
Caracas — aunque no siempre cumple. Así que se mira cada dos horas de forma normal, cada media hora
entre las 3 y las 9 de la noche, y **en cuanto aparece la tasa del día siguiente se deja de preguntar
hasta mañana**. Eso baja de 48 consultas diarias a unas diez. La página del BCV pesa 150 KB y es de un
organismo público: se raspa una vez por tasa nueva, sólo para contrastar.

## Por qué existe esto

Porque **ninguna fuente guarda el histórico**. Todos los endpoints de series históricas que probé
devuelven 404. Si nadie anota la tasa de cada día, el día que tu teléfono esté apagado esa tasa se
pierde para siempre, y las operaciones de esa fecha ya no se pueden valorar bien.

Y porque una sola consulta compartida es mejor que muchas: si cada app preguntara por su cuenta,
multiplicaríamos las llamadas por cada usuario, y el endpoint de Binance —que no es oficial— acabaría
bloqueándonos. Leer un archivo publicado, en cambio, no tiene límite.

## Cómo se usa

```
https://raw.githubusercontent.com/mi-url/tasas-venezuela/main/tasas.json
```

Quien lo consuma debería mirar el campo `actualizado` y **decir en pantalla si el dato está viejo**. El
servicio anterior estuvo seis meses sirviendo una tasa de 339 bolívares cuando el dólar estaba en 746, y
nadie se enteró porque nada mostraba la fecha. Ése es el fallo que no se puede repetir.

## Correrlo a mano

```bash
python3 registrar.py          # consulta y actualiza los archivos
python3 -m unittest test_registrar -v
```

Sin dependencias: sólo la librería estándar de Python.
