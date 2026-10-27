# Tasas de cambio de Venezuela

Registro público y automático de a cuánto está el bolívar. Se actualiza solo cada media hora y guarda
el histórico, que es lo que ninguna fuente pública ofrece.

**Lo último está en [`tasas.json`](tasas.json).** El histórico, en [`historico/`](historico), un archivo
por mes con una línea por consulta. Y **el BCV de cada día desde 2020**, en
[`historico/bcv-oficial.jsonl`](historico/bcv-oficial.jsonl): ver [La serie oficial del BCV](#la-serie-oficial-del-bcv-desde-2020).
Y **el mercado de cada día de antes del registrador**, recopilado una vez de cuatro fuentes públicas, en
[`historico/mercado-anterior.jsonl`](historico/mercado-anterior.jsonl): ver [El mercado de antes](#el-mercado-de-antes-de-2020-a-julio-de-2026).

## Qué publica

| Clave | Qué es | De dónde sale |
|---|---|---|
| `ves_por_usd_bcv` | El dólar oficial del Banco Central | la página del BCV, `bcv.org.ve` |
| `ves_por_eur_bcv` | El euro oficial, que muchos comercios usan | la página del BCV, en el mismo vistazo |
| `ves_por_usdt_mercado` | La tasa de la calle: lo que te dan por vender un USDT, y en `compra` lo que cuesta comprarlo | Binance P2P |
| `internacionales` | Divisas estándar contra el dólar | Banco Central Europeo, vía `frankfurter.dev` |
| `criptomonedas` | Bitcoin y USDT contra el dólar | CoinGecko |

USDT vale *casi* un dólar, y *casi* no es *exactamente*: darlo por supuesto arrastra un error pequeño en
cada operación que acaba sumando. Se pregunta y se guarda como cualquier otra tasa.

**Cada clave dice en qué unidad está.** `ves_por_usd` son bolívares por un dólar, no al revés. Puede
parecer pedante hasta que se mezclan las dos: confundirlas es lo que hace que un sistema registre una
ganancia de noventa mil dólares sobre diez.

**Ninguna cifra pasa por un número de coma flotante.** Cada una se guarda tal como la dio su fuente, con
todos sus decimales aunque traiga más de ocho. Sólo se redondea lo que se calcula aquí: la dispersión de
Binance y las inversas de las criptomonedas. Y lo de la serie oficial, porque el BCV guarda sus .xls con
números del Excel: cada uno se redondea a los ocho decimales que publica, y se escribe como texto.

Y cada dato viene con **de dónde salió y cuándo**. Una tasa sin fecha es una tasa en la que no se puede
confiar.

## Desde cuándo rige una tasa del BCV

El BCV publica hacia las 4:30 de la tarde, a veces antes y a veces hacia las 5, y **lo que publica rige
desde ese momento hasta que publique la siguiente**. La del viernes rige el fin de semana y el lunes, y un
feriado bancario no publica: sigue la última.

Por eso cada publicación lleva, además de su `fecha_valor`, estas marcas. **Cada moneda lleva las suyas**:
el BCV a veces corrige sólo el euro, y entonces cambian las del euro y las del dólar se quedan como
estaban. Decir que el dólar «no estaba» a una hora en que ya estaba sería falso, y quien lo lee movería
desde cuándo rige.

| Campo | Qué es |
|---|---|
| `publicado_visto` | El momento en que el registrador la vio por primera vez: **desde cuándo rige** |
| `no_estaba_a_las` | La última vez que **la página** enseñaba la de antes. Entre las dos queda acotado cuándo publicó el BCV |
| `visto_por` | Quién la vio primero: `bcv.org.ve` o, si la página estaba caída, `dolarapi` |
| `respaldo` | `true` cuando la vio primero dolarapi: su `publicado_visto` es cuándo la dio dolarapi, que llega tarde, no cuándo publicó el BCV. Se mantiene hasta la publicación siguiente |
| `obtenido` | El momento de la lectura que trajo esa cifra. Volver a leer la misma no lo mueve |
| `consultado` | La última vez que se leyó la página. Una lectura de dolarapi no lo mueve |

`no_estaba_a_las` vacío quiere decir que no se sabe desde cuándo estaba. Pasa con la primera publicación
que recogió esta versión, porque la anterior no guardaba cuándo miraba. Si la página estuvo caída un
rato, el hueco entre `no_estaba_a_las` y `publicado_visto` es más largo, y es verdad: es lo que se sabe.

La `fecha_valor` no dice desde cuándo rige: sólo sirve para reconocer que salió una publicación nueva.

**Una cifra del BCV sin su coma decimal no se lee.** La página las escribe a la venezolana, `887,30200000`,
con punto de miles y coma decimal. Si un día la escribiera con punto decimal, quitarle los puntos de miles
la multiplicaría por cien millones; por eso una cifra que no tenga esa forma cuenta como página caída.

## Las decisiones que no son obvias

**El BCV se lee de su página, no de dolarapi.** dolarapi cambia a la tasa nueva a la medianoche de su
fecha valor, no cuando el BCV la publica: medido en septiembre de 2026, cada tasa nueva aparecía a las
5:23 de la mañana. Entre semana eso son unas siete horas y media tarde, y con un fin de semana de por
medio, días. dolarapi se queda de respaldo, sólo si la página no contesta, y **sólo cuenta si trae una
publicación de fecha posterior a la que ya se tiene**: con la misma fecha no trae nada nuevo (o es la
misma, o es una versión sin la corrección que la página ya dio), y con una anterior es una fuente
atrasada.

**Al BCV se le mira cada media hora desde las 3:30 de la tarde de Caracas, hasta que la página enseña la
nueva.** Que la diera dolarapi no cuenta: no dice cuándo publicó el BCV. Ya vista, se mira una vez más
después de las 10 de la noche por si la corrigió, y una vez por la mañana. Se empieza a las 3:30 y no a
las 4 porque el BCV a veces se adelanta. La página pesa 150 KB y es de un organismo público: se mira sólo
lo que hace falta.

**El certificado del BCV, sin apagar la seguridad.** Su servidor manda mal la cadena: el intermedio que
hace falta no es el que envía, y por eso Python no podía leer la página. En
[`certificados/intermedios-bcv.pem`](certificados/intermedios-bcv.pem) van los dos eslabones que faltan,
de Sectigo, y la cadena se verifica entera hasta una raíz de confianza del sistema. **Su certificado vence
el 2026-11-20**: si el nuevo lo firma otro intermedio que el servidor tampoco mande, el registrador lee
del propio certificado de dónde se baja, lo baja y lo añade, como hace un navegador. Lo bajado sólo
completa la cadena: la conexión sigue exigiendo una raíz de confianza.

**De Binance cuentan sólo los anuncios de una operación normal, y se usa la mediana.** Se piden los diez
primeros que aceptan unos 100 dólares en bolívares, calculados con la última tasa, y se toma la mediana.
Sin ese filtro salen anuncios que no son el precio de nadie: el 2026-10-25 el primero de un lado estaba a
980,54 con un límite de 300 a 400 bolívares, y los primeros del otro pedían mínimos de tres millones. La
mediana, además, no se mueve por un anuncio raro que se cuele arriba. Con el filtro, la venta salió
1.003,05 y el paralelo de dolarapi, 1.002,95.

**En la API de Binance, `tradeType` es lo que hace quien consulta.** `SELL` trae a quien compra USDT: es
lo que te dan por vender uno, que es la tasa de mercado. `BUY` trae a quien vende: lo que cuesta
comprarlo.

**Una fuente que falla no tumba a las demás.** Si una no contesta, contesta algo que no es lo esperado
o revienta por algo que nadie previó, se repite su dato anterior **con su hora de entonces** y se apunta
en `fallos`; las otras se publican igual. Una pasada tiene además un tope de tres minutos y medio para
consultar, para que GitHub no la corte sin publicar nada. La alarma está en la app, que dice de cuándo es
cada tasa.

## La serie oficial del BCV, desde 2020

El registrador apunta el BCV desde el 2026-07-31. **Lo de antes lo tiene el propio BCV**, en su serie
«Tipo de Cambio de Referencia SMC»: un .xls por trimestre desde el primero de 2020, con una hoja por
día. [`importar_bcv_oficial.py`](importar_bcv_oficial.py) los lee todos y escribe
[`historico/bcv-oficial.jsonl`](historico/bcv-oficial.jsonl), **una línea por fecha valor**:

| Campo | Qué es |
|---|---|
| `fecha_valor` | El día en que rige, como lo escribe el BCV |
| `fecha_operacion` | El día de la hoja: el día hábil en que el BCV la sacó |
| `ves_por_usd`, `ves_por_eur` | La venta (ASK) en bolívares de hoy, como texto exacto |
| `escala_original` | `bolívar digital` o, hasta la fecha valor 2021-09-30, `bolívar soberano` |
| `cifras_originales` | Sólo en soberanos: las cifras tal como las da la hoja |
| `hora_de_la_hoja` | La hora que estampa el BCV en la hoja, en hora de Caracas. No se sabe si es la de publicación: **no dice desde cuándo rige** |
| `fuente` | `bcv.org.ve (serie oficial)` |
| `archivo`, `hoja` | De qué .xls y de qué hoja salió |
| `obtenido` | Cuándo entró esa línea en la serie |

- **Las cifras de antes del 2021-10-01 se dividen entre un millón.** Ese día entró el bolívar digital, un
  millón de soberanos cada uno; la primera fecha valor en digitales es la del 2021-10-04. La división es
  exacta: sólo se corre la coma.
- **El BCV guarda sus cifras como números del Excel**, y publica ocho decimales: cada una se redondea a
  ocho. En el .xls del tercer trimestre de 2026, los 4.116 números de sus hojas vuelven exactos así.
- **Los enlaces de cada trimestre se leen de la página de la serie, no se arman**: un trimestre que el BCV
  vuelve a subir cambia de nombre (`2_1_2c23_smc_60.xls`).
- **Se puede volver a correr.** Lo que ya estaba no cambia ni un byte; se vuelve a leer desde el trimestre
  de la última fecha de operación que se tiene, y entra lo nuevo. Si una fecha que ya estaba sale con otra
  cifra, no se toca nada y se dice.
- **Si el BCV cambia la forma de la hoja, no se publica nada**, y el error dice qué hoja y qué le falta.

Lo corre a mano el flujo [`importar-bcv-oficial.yml`](.github/workflows/importar-bcv-oficial.yml), aparte
del de cada media hora. Después, [`contrastar_bcv_oficial.py`](contrastar_bcv_oficial.py) dice en el
resumen de la ejecución cuántas fechas coinciden con lo que apuntó el registrador y con frankfurter, que
lee los mismos .xls desde el 2021-10-04. Con el .xls del tercer trimestre de 2026 coinciden las 29 fechas
valor que tiene el registrador (del 31 de julio al 9 de septiembre) y las 49 de frankfurter, dólar y euro.

## El mercado de antes, de 2020 a julio de 2026

El registrador mide el mercado desde el 2026-07-31. **Lo de antes no lo midió nadie de aquí**, así que se
recopiló **una sola vez**, el 2026-10-27, de cuatro fuentes públicas, en
[`historico/mercado-anterior.jsonl`](historico/mercado-anterior.jsonl): **una línea por día**, del
2020-03-30 (el primer día de la serie oficial del BCV) al 2026-07-30. **Está congelado**: ningún flujo lo
toca. Lo armó [`compilar_mercado_anterior.py`](compilar_mercado_anterior.py), que explica cada decisión.

| Campo | Qué es |
|---|---|
| `fecha` | El día, en Caracas |
| `ves_por_usd` | Los bolívares de hoy por un dólar, como texto exacto |
| `fuente` | De cuál de las cuatro es la cifra |
| `escala_original`, `cifra_original` | Sólo si la fuente la daba en soberanos: `bolívar soberano` y la cifra tal cual |
| `testigos` | Lo que decían ese día las otras fuentes, para comparar. No se usa para nada más |
| `obtenido` | Cuándo se bajó la fuente |

**Una cifra por día, de una sola fuente, tal cual.** Nunca se mezclan dos ni se corrige una con otra. Qué
fuente manda se eligió midiendo cuál se parece más al mercado de este registrador. Ese mercado casa con el
paralelo de dolarapi: el 26 de octubre de 2026, lectura a lectura, a un 0,03 %, y en el promedio de ese día y
del siguiente, a menos de un 0,3 %.

| Días | Fuente | Qué es | Días con cifra |
|---|---|---|---|
| 2020-03-30 a 2025-05-27 | [xjp.cl](https://xjp.cl), `Parallel_Daily_Full.csv` | El paralelo de DolarToday y EnParaleloVzla, el cierre de cada día hábil | 1.239 |
| | si falta: [Wikipedia](https://es.wikipedia.org/wiki/Anexo:Cotizaci%C3%B3n_hist%C3%B3rica_del_bol%C3%ADvar_con_respecto_al_d%C3%B3lar) | El de Monitor Dólar, que el anexo anota a mano | 63 |
| 2025-05-28 a 2025-10-27 | [CriptoDólar](https://criptodolar.net), «Dólar Binance» | Una foto de Binance P2P hacia las 7 de la tarde: el paralelo dejó de publicarse | 131 |
| | si falta: Wikipedia | | 16 |
| 2025-10-28 a 2026-07-30 | [Yadio](https://yadio.io), `hist/365` | El promedio de 24 horas de cada día (días de UTC, de 8 a 8 de la noche de Caracas) | 276 |

- **1.725 días con cifra de 2.314.** De los 589 sin cifra:
  - 538 son fines de semana de 2020 a mayo de 2025, que el paralelo no publicaba y no se rellenan con otra
    fuente: cada lunes daría un salto que no fue del mercado;
  - 6 son fines de semana de junio de 2025 sin foto de CriptoDólar;
  - y 45 son días hábiles, la mayoría feriados, en que no hay cifra o la que hay es una errata.
- **Contra el paralelo de dolarapi**, de febrero a julio de 2026, Yadio sale un 0,36 % por debajo y nunca a
  más de un 3,6 %. CriptoDólar, un 1,84 % por encima y con 15 días a más de un 5 %: por eso sólo cubre el
  tramo en que no hubo paralelo.
- **Las dos costuras con el registrador no son del mercado.** El método del registrador de antes del
  2026-10-26 salía un 1,75 % por encima de Yadio: el 2026-07-31 sube eso de golpe, y el 2026-10-26 baja otro
  tanto al cambiar de método.
- **2020 es aproximado en todas las fuentes.** Con la hiperinflación el paralelo se movía hasta un 10 % en
  un día, y cada fuente lo anota a una hora: xjp.cl y Wikipedia se separan más de un 5 % en 24 días de 2020.
- **Los soberanos se dividen entre un millón, exacto**: todo xjp.cl, que nunca aplicó la reconversión de
  2021, y Wikipedia hasta el 2021-09-30. Lo que la fuente da como número binario (CriptoDólar, Yadio) se
  redondea a ocho decimales, como la serie oficial del BCV.
- **Siete cifras se quitaron**, sin corregirlas, cada una comprobada contra las demás fuentes:
  - xjp.cl, el 2020-06-10, el 2020-11-09 y el 2020-12-15;
  - Wikipedia, el 2025-11-21 y el 2026-06-12, erratas de tecleo;
  - y el 2021-09-30 y el 2021-10-01, dos del Monitor Dólar de la reconversión, un 18-20 % por encima de todo
    lo demás.

  El script se niega a publicar si encuentra otra.
- **Lo que no se lee sin dudar, no se lee.** Dos celdas de Wikipedia escriben `8 88` y `24 80`, con un
  espacio por coma, y se quedan sin leer: ese día manda xjp.cl.
- **Se probó y se descartó LocalBitcoins** para 2020-2021 (la tasa que se deduce de UsefulTulips): sale un
  2-3 % por debajo de los dos paralelos.

**Las fuentes no se copian aquí**, se citan: xjp.cl publica sus datos con licencia
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), como dice su portada; el anexo de Wikipedia, con
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) (revisión 175956434, del 2026-10-23); Yadio
pide citarlo con un enlace, y aquí está; CriptoDólar no declara licencia para sus cifras. De cada una se toma
sólo la cifra de cada día.

Para volver a armarlo hacen falta las cuatro fuentes tal como se bajaron, en una carpeta:

```bash
python3 compilar_mercado_anterior.py <carpeta>    # escribe historico/mercado-anterior.jsonl
python3 -m unittest test_mercado_anterior -v      # las pruebas del archivo y de cada lector
```

Las pruebas se corren al cambiar la recopilación: el archivo está congelado, y el registrador de cada media
hora no depende de él.

## Por qué existe esto

Porque **ninguna fuente guarda el histórico**. Si nadie anota la tasa de cada día, el día que tu teléfono
esté apagado esa tasa se pierde para siempre, y las operaciones de esa fecha ya no se pueden valorar bien.

Y porque una sola consulta compartida es mejor que muchas: si cada app preguntara por su cuenta,
multiplicaríamos las llamadas por cada usuario, y el endpoint de Binance —que no es oficial— acabaría
bloqueándonos. Leer un archivo publicado, en cambio, no tiene límite.

## Quién la despierta

**Un despertador, no el reloj de GitHub.** El reloj de GitHub dispara los horarios cuando puede: el
2026-10-26 lanzó 4 pasadas de unas 39 en 19 horas, cada una entre 20 y 50 minutos tarde, y en su foro hay
quejas iguales desde agosto de 2026. Una pasada pedida por su API, en cambio, arranca al momento.

Así que un trabajo gratis de `cron-job.org` le pide a GitHub, a los 17 y a los 47 de cada hora, que corra
este flujo (`POST /repos/mi-url/tasas-venezuela/actions/workflows/registrar.yml/dispatches`, con
`{"ref":"main"}`). Usa una llave de grano fino que sólo sirve para lanzar tareas de este repositorio
(«Actions: Read and write»), y vence el 2027-10-26: antes de esa fecha hay que poner una nueva.

El horario de GitHub se queda en el flujo como respaldo. Una pasada de más no estorba: espera a la que está
corriendo, y si nada cambió no publica nada.

## Cuánto cuesta

Nada. Corre en GitHub Actions, en un repositorio público y con las máquinas normales de GitHub, que no se
cobran. Son unas 48 pasadas de medio minuto al día, y nada se queda encendido esperando. El despertador de
cron-job.org también es gratis.

## Cómo se usa

```
https://raw.githubusercontent.com/mi-url/tasas-venezuela/main/tasas.json
```

Quien lo consuma debería **decir en pantalla de cuándo es cada tasa**. El servicio anterior estuvo seis
meses sirviendo una tasa de 339 bolívares cuando el dólar estaba en 746, y nadie se enteró porque nada
mostraba la fecha. Ése es el fallo que no se puede repetir.

## Correrlo a mano

```bash
python3 registrar.py                     # consulta y actualiza los archivos
python3 -m unittest test_registrar -v    # las pruebas, con respuestas reales guardadas en pruebas/
```

El registrador no tiene dependencias: sólo la librería estándar de Python. La serie oficial necesita un
lector de .xls, `xlrd`, fijado con su huella:

```bash
python3 -m pip install --require-hashes -r requisitos-serie-oficial.txt
python3 importar_bcv_oficial.py                     # lee lo que falta de la serie y la escribe
python3 contrastar_bcv_oficial.py                   # la compara con el registrador y con frankfurter
python3 -m unittest test_importar_bcv_oficial -v    # sus pruebas, con el .xls real del BCV en pruebas/
```
