# Qullamaggie · BingX Scanner & Trading Bot

Escanea **todos los perpetuos USDT de BingX** buscando movimientos explosivos intradía (largos y cortos), envía las señales a **Telegram** y, opcionalmente, opera en BingX. Pensado para desplegarse en **Railway**.

> ⚠️ **Aviso:** esto es software experimental, no asesoramiento financiero. Operar con apalancamiento puede hacerte perder todo el capital. Los parámetros no están optimizados ni validados con backtest. **Empieza en modo `signals`, luego `paper`, luego demo, y solo después `live` con poco dinero.**

## Qué detecta

| Setup | Idea (Qullamaggie adaptada a cripto) | Lado |
|---|---|---|
| **Breakout / Breakdown** | Activo con ADR alto y tendencia previa (EMA10>EMA20) que consolida en rango tenso (rango contraído, higher lows / lower highs) y rompe en 15m con volumen relativo ≥ 2x | Long / Short |
| **Episodic Pivot** | Vela 15m explosiva (≥3%) con RVOL ≥ 4x que rompe el máx/mín de 24h en un activo que no venía extendido | Long / Short |
| **Parabolic Short** | Subida ≥ 40% en 5 días y muy extendida sobre la EMA20 diaria; entra corto al perder el VWAP de la sesión | Short |

**Ideas añadidas:** score 0-100, filtro de régimen de BTC (a favor +8 / en contra −12), filtro de funding (crowding), stop técnico acotado por ATR (se descarta si queda lejos), prefiltro por volumen relativo para escanear rápido, cooldown por moneda, límites diarios de operaciones y pérdida, parcial en TP1 + break-even + trailing por EMA, salida por tiempo.

## Gestión de la operación
1. Entrada a mercado tras cerrar la vela 15m de señal.
2. Stop técnico: en **live** se coloca como orden en BingX y además lo vigila el bot. Si no se puede colocar el stop, la posición se cierra al instante.
3. Al llegar a `TP1_R` (1.5R) cierra `PARTIAL_PCT` (50%) y mueve el stop a break-even.
4. El resto sigue con trailing por EMA10 de 1h. Salida por tiempo a las 24h.

## Despliegue paso a paso

### 1. Telegram
1. Habla con **@BotFather** → `/newbot` → copia el **token**.
2. Escribe cualquier mensaje a tu bot, abre `https://api.telegram.org/bot<TOKEN>/getUpdates` y copia tu `chat.id`.

### 2. BingX (solo para paper con precios públicos no hace falta; sí para live)
- Crea una API key en BingX **sin permiso de retiro** (solo lectura + trading de futuros).
- Railway no tiene IP de salida fija en el plan básico: no actives lista blanca de IP, o usa una IP estática.
- Prueba antes con la cuenta demo (`BINGX_DEMO=true`).

### 3. GitHub
```bash
git init && git add . && git commit -m "bot inicial"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/qulla-bingx-bot.git
git push -u origin main
```
(El archivo `.env` está en `.gitignore`: **nunca subas tus claves**.)

### 4. Railway
1. **New Project → Deploy from GitHub repo** y elige el repositorio.
2. En **Variables** añade las del archivo `.env.example` (mínimo: `TRADING_MODE`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`).
3. **Settings → Region**: elige una región de **Europa o Asia**. BingX bloquea algunas IP de EE. UU.
4. **Volume** (recomendado): añade un volumen montado en `/data` y pon `DATA_DIR=/data` para conservar el estado entre reinicios.
5. El comando de inicio ya está en `railway.json`/`Procfile`: `python main.py`.
6. Deberías recibir en Telegram el mensaje «bot iniciado».

### Ejecución local
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # edítalo
set -a && source .env && set +a
python main.py
pytest                 # tests de estrategia y gestión
```

## Comandos de Telegram
`/status` · `/positions` · `/pause` (no abre nuevas) · `/resume` · `/closeall` (cierra todo)

## Variables principales
| Variable | Defecto | Descripción |
|---|---|---|
| `TRADING_MODE` | `signals` | `signals`, `paper` o `live` |
| `RISK_PER_TRADE_PCT` | 0.5 | % del equity arriesgado por operación |
| `LEVERAGE` / `MAX_MARGIN_PCT` | 5 / 20 | Apalancamiento y margen máximo por operación |
| `MAX_OPEN_POSITIONS` | 3 | Posiciones simultáneas |
| `MAX_TRADES_PER_DAY` / `DAILY_LOSS_LIMIT_PCT` | 6 / 3 | Frenos diarios (UTC) |
| `MIN_SCORE` | 65 | Score mínimo para avisar/operar |
| `MIN_24H_VOLUME_USD` | 3000000 | Liquidez mínima por moneda |
| `ADR_MIN_PCT`, `RVOL_MIN`, `RUNUP_MIN_PCT`… | ver `config.py` | Parámetros de cada setup |
| `HEDGE_MODE` | true | Pon `false` si tu cuenta BingX es One-Way |

## Estructura
```
bot/config.py      variables de entorno        bot/strategies.py  setups, score, régimen, funding
bot/scanner.py     escaneo de todo BingX       bot/trader.py      órdenes, stops, TP1, trailing
bot/telegram.py    avisos y comandos           bot/state.py       estado persistente (JSON)
bot/main.py        hilos: escaneo/gestión/cmd  tests/             pruebas con datos sintéticos
```

## Limitaciones conocidas
- La integración con BingX (órdenes stop, modo hedge, demo) **no se ha probado contra el exchange real**; verifícala primero en la cuenta demo con importes mínimos y revisa que cada entrada tenga su stop en BingX.
- Los símbolos y la API de BingX cambian: si una orden falla, el bot avisa por Telegram.
- El PnL en live es una estimación; el valor real está en BingX.
- Sin backtest incluido: calibra los umbrales observando las señales en modo `signals`.
