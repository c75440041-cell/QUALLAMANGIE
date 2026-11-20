from __future__ import annotations

import logging
import signal
import sys
import threading
import time

from config import load_config
from exchange import make_exchange
from scanner import Scanner
from state import State
from telegram import Notifier
from trader import Trader, px

logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
log = logging.getLogger("main")


def fmt_signal(s, regime: str, cfg) -> str:
    long = s.side == "long"
    d = 1 if long else -1
    tp1 = s.entry + d * cfg.tp1_r * s.risk
    return (
        f"{'🟢' if long else '🔴'} <b>{s.side.upper()} {s.symbol}</b> · {s.setup}\n"
        f"Score <b>{s.score:.0f}/100</b> | BTC: {regime}\n"
        f"Entrada ≈ {px(s.entry)}\n"
        f"SL {px(s.stop)} ({s.risk / s.entry * 100:.2f}%) | TP1 {px(tp1)} ({cfg.tp1_r}R)\n"
        f"Plan: {cfg.partial_pct:.0f}% en TP1, stop a break-even y trailing EMA{cfg.trail_ema} {cfg.trail_tf}\n"
        + "\n".join(f"• {r}" for r in s.reasons)
    )


def fmt_day(prev: dict) -> str:
    return (f"📊 <b>Resumen {prev['date']}</b>\nOperaciones: {prev['trades']} | "
            f"PnL realizado: ${prev['realized']:+.2f}")


def main():
    cfg = load_config()
    if cfg.mode == "live" and not (cfg.api_key and cfg.api_secret):
        raise SystemExit("TRADING_MODE=live requiere BINGX_API_KEY y BINGX_API_SECRET")

    st = State(cfg.data_dir, cfg.paper_equity)
    tg = Notifier(cfg)
    scan_ex = make_exchange(cfg, auth=False)                 # datos públicos, sin claves
    trade_ex = make_exchange(cfg, auth=cfg.mode == "live")
    scanner = Scanner(scan_ex, cfg)
    trader = Trader(trade_ex, cfg, st, tg.send)
    stop = threading.Event()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())

    def scan_loop():
        while not stop.is_set():
            t0 = time.time()
            try:
                signals, regime = scanner.scan()
                for s in [x for x in signals if x.score >= cfg.min_score][: cfg.max_signals_per_scan]:
                    if st.cooldown_active(s.symbol, cfg.cooldown_min):
                        continue
                    tg.send(fmt_signal(s, regime, cfg))
                    st.set_cooldown(s.symbol)
                    if cfg.mode != "signals":
                        ok, why = trader.open(s)
                        if not ok:
                            tg.send(f"⏭ {s.symbol} no ejecutada: {why}")
            except Exception as e:
                log.exception("scan error")
                tg.alert_once("scan", f"⚠️ Error en el escaneo: {e}")
            stop.wait(max(5, cfg.scan_interval - (time.time() - t0)))

    def manage_loop():
        while not stop.is_set():
            try:
                prev = st.ensure_day(trader.equity)
                if prev:
                    tg.send(fmt_day(prev))
                trader.manage()
            except Exception as e:
                log.exception("manage error")
                tg.alert_once("manage", f"⚠️ Error gestionando posiciones: {e}")
            stop.wait(cfg.manage_interval)

    def cmd_pause():
        st.data["paused"] = True
        st.save()
        return "⏸ Bot en pausa: no abrirá nuevas operaciones (las abiertas se siguen gestionando)."

    def cmd_resume():
        st.data["paused"] = False
        st.save()
        return "▶️ Bot reanudado."

    def cmd_closeall():
        return f"🧹 Posiciones cerradas: {trader.close_all()}"

    handlers = {
        "/status": trader.summary,
        "/positions": trader.positions_text,
        "/pause": cmd_pause,
        "/resume": cmd_resume,
        "/closeall": cmd_closeall,
        "/help": lambda: "/status /positions /pause /resume /closeall",
    }

    prev = st.ensure_day(trader.equity)
    tg.send(
        f"🤖 <b>Qullamaggie-BingX bot iniciado</b>\n"
        f"Modo: <b>{cfg.mode.upper()}</b>{' (DEMO)' if cfg.demo else ''} | Escaneo cada {cfg.scan_interval}s\n"
        f"Riesgo/op {cfg.risk_pct}% | Lev {cfg.leverage}x | Score mín {cfg.min_score:.0f}\n"
        f"Comandos: /status /positions /pause /resume /closeall"
    )
    for fn in (scan_loop, manage_loop, lambda: tg.listen(handlers, stop)):
        threading.Thread(target=fn, daemon=True).start()
    stop.wait()
    log.info("Apagando...")


if __name__ == "__main__":
    main()
