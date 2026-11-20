"""
Setups inspirados en Qullamaggie, adaptados a cripto intradía:

  1. Breakout / Breakdown : ruptura de una consolidación tensa (higher lows / lower highs,
                            rango contraído) en un activo con ADR alto y tendencia previa.
  2. Episodic Pivot       : vela explosiva con volumen anómalo que rompe el máximo/mínimo de 24h
                            en un activo que NO venía ya extendido.
  3. Parabolic Short      : subida vertical (+40% en 5d) muy extendida sobre la EMA20 diaria;
                            se entra corto al perder el VWAP de la sesión.

Todas las funciones trabajan con velas CERRADAS (15m y 1h). Diario incluye la vela de hoy.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from indicators import adr_pct, atr, ema, rvol, session_vwap


@dataclass
class Signal:
    symbol: str
    side: str            # "long" | "short"
    setup: str
    entry: float
    stop: float
    score: float
    reasons: list = field(default_factory=list)
    atr1h: float = 0.0

    @property
    def risk(self) -> float:
        return abs(self.entry - self.stop)


def _stop(side: str, entry: float, raw: float, atr1h: float, cfg):
    """Stop técnico acotado por ATR: si queda muy lejos, el setup se descarta."""
    dist = max(abs(entry - raw), cfg.min_stop_atr * atr1h)
    if dist > cfg.max_stop_atr * atr1h or dist / entry * 100 > cfg.max_stop_pct:
        return None
    return entry - dist if side == "long" else entry + dist


def daily_ctx(d):
    c = d["close"]
    e10, e20 = ema(c, 10), ema(c, 20)
    return {
        "close": float(c.iloc[-1]),
        "e10": float(e10.iloc[-1]),
        "e20": float(e20.iloc[-1]),
        "adr": adr_pct(d, 20),
        "atr": float(atr(d, 14).iloc[-1]),
        "runup30": float((c.iloc[-1] / d["low"].tail(30).min() - 1) * 100),
        "drop30": float((1 - c.iloc[-1] / d["high"].tail(30).max()) * 100),
        "gain5": float((c.iloc[-1] / c.iloc[-6] - 1) * 100),
    }


def _consolidation_break(sym, side, ctx, h, m, a1h, cfg):
    long = side == "long"
    if ctx["adr"] < cfg.adr_min:
        return None
    if long:
        if not (ctx["close"] > ctx["e20"] and ctx["e10"] > ctx["e20"] and ctx["runup30"] >= cfg.runup_min):
            return None
        prior = ctx["runup30"]
    else:
        if not (ctx["close"] < ctx["e20"] and ctx["e10"] < ctx["e20"] and ctx["drop30"] >= cfg.runup_min):
            return None
        prior = ctx["drop30"]

    w = h.tail(cfg.consol_bars)
    hi, lo = float(w["high"].max()), float(w["low"].min())
    rng = (hi / lo - 1) * 100
    max_rng = cfg.consol_range_adr * ctx["adr"]
    if rng > max_rng:
        return None
    half = len(w) // 2
    tr = w["high"] - w["low"]
    if not tr.iloc[half:].mean() < tr.iloc[:half].mean():          # contracción de rango
        return None
    if long and not w["low"].iloc[half:].min() >= w["low"].iloc[:half].min():      # higher lows
        return None
    if not long and not w["high"].iloc[half:].max() <= w["high"].iloc[:half].max():  # lower highs
        return None

    last, prev = m.iloc[-1], m.iloc[-2]
    rv = rvol(m, 20)
    if rv < cfg.rvol_min:
        return None
    if long:
        if not (last["close"] > hi and prev["close"] <= hi and last["close"] > last["open"]):
            return None
        chase = (last["close"] / hi - 1) * 100
    else:
        if not (last["close"] < lo and prev["close"] >= lo and last["close"] < last["open"]):
            return None
        chase = (lo / last["close"] - 1) * 100
    if chase > cfg.max_chase_pct:
        return None

    entry = float(last["close"])
    stop = _stop(side, entry, lo if long else hi, a1h, cfg)
    if stop is None:
        return None

    score = (
        55
        + min(15, (rv - cfg.rvol_min) * 5)
        + min(10, (ctx["adr"] - cfg.adr_min) * 2)
        + min(10, max(0.0, (prior - cfg.runup_min) / 3))
        + max(0.0, (1 - rng / max_rng) * 10)
    )
    name = "Breakout" if long else "Breakdown"
    reasons = [
        f"ADR {ctx['adr']:.1f}%",
        f"{'Subida' if long else 'Caída'} 30d {prior:.0f}%",
        f"Consolidación 1h {rng:.2f}% (contraída)",
        f"Ruptura 15m con RVOL {rv:.1f}x",
    ]
    return Signal(sym, side, name, entry, stop, min(100.0, score), reasons, a1h)


def _episodic(sym, side, ctx, m, a1h, cfg):
    long = side == "long"
    last = m.iloc[-1]
    rng = float(last["high"] - last["low"])
    if rng <= 0:
        return None
    move = (last["close"] / last["open"] - 1) * 100
    rv = rvol(m, 20)
    if rv < cfg.ep_rvol:
        return None
    window = m.iloc[-97:-1]
    if long:
        if not (move >= cfg.ep_move_15m and (last["close"] - last["low"]) / rng >= 0.75
                and last["close"] > window["high"].max() and ctx["runup30"] < cfg.ep_max_prior):
            return None
        raw = float(last["low"])
    else:
        if not (move <= -cfg.ep_move_15m and (last["high"] - last["close"]) / rng >= 0.75
                and last["close"] < window["low"].min() and ctx["drop30"] < cfg.ep_max_prior):
            return None
        raw = float(last["high"])
    entry = float(last["close"])
    stop = _stop(side, entry, raw, a1h, cfg)
    if stop is None:
        return None
    score = 60 + min(20, (rv - cfg.ep_rvol) * 3) + min(10, (abs(move) - cfg.ep_move_15m) * 3)
    reasons = [
        f"Impulso 15m {move:+.1f}%",
        f"RVOL {rv:.1f}x",
        "Rompe máx/mín de 24h",
        "Activo no extendido previamente",
    ]
    return Signal(sym, side, "Episodic Pivot", entry, stop, min(100.0, score), reasons, a1h)


def _parabolic_short(sym, ctx, m, a1h, cfg):
    if ctx["gain5"] < cfg.para_gain5:
        return None
    ext = (ctx["close"] - ctx["e20"]) / ctx["atr"] if ctx["atr"] > 0 else 0.0
    if ext < cfg.para_ext_atr:
        return None
    vw = session_vwap(m)
    day = m["ts"] // 86_400_000
    today = m[day == day.iloc[-1]]
    if len(today) < 4:
        return None
    day_high = float(today["high"].max())
    last, prev = m.iloc[-1], m.iloc[-2]
    if not (prev["close"] >= vw.iloc[-2] and last["close"] < vw.iloc[-1] and last["close"] < last["open"]):
        return None
    if (day_high / vw.iloc[-1] - 1) * 100 < 2.0:
        return None
    entry = float(last["close"])
    stop = _stop("short", entry, day_high * 1.001, a1h, cfg)
    if stop is None:
        return None
    rv = rvol(m, 20)
    score = (
        58
        + min(15, (ctx["gain5"] - cfg.para_gain5) / 4)
        + min(15, (ext - cfg.para_ext_atr) * 3)
        + (5 if rv >= 1.5 else 0)
    )
    reasons = [
        f"Subida 5d {ctx['gain5']:.0f}%",
        f"{ext:.1f} ATR sobre EMA20 diaria",
        "Pierde VWAP de la sesión",
        f"Máx del día a {(day_high / entry - 1) * 100:.1f}% sobre entrada",
    ]
    return Signal(sym, "short", "Parabolic Short", entry, stop, min(100.0, score), reasons, a1h)


def evaluate(sym, d, h, m, cfg) -> list:
    """d: diario (incluye hoy) | h: 1h cerradas | m: 15m cerradas."""
    if len(d) < 30 or len(h) < 60 or len(m) < 110:
        return []
    ctx = daily_ctx(d)
    a1h = float(atr(h, 14).iloc[-1])
    if a1h <= 0:
        return []
    out = []
    if cfg.enable_longs:
        out.append(_consolidation_break(sym, "long", ctx, h, m, a1h, cfg))
        out.append(_episodic(sym, "long", ctx, m, a1h, cfg))
    if cfg.enable_shorts:
        out.append(_consolidation_break(sym, "short", ctx, h, m, a1h, cfg))
        out.append(_episodic(sym, "short", ctx, m, a1h, cfg))
        out.append(_parabolic_short(sym, ctx, m, a1h, cfg))
    return [s for s in out if s]


def btc_regime(h) -> str:
    c = h["close"]
    e20, e50 = float(ema(c, 20).iloc[-1]), float(ema(c, 50).iloc[-1])
    last = float(c.iloc[-1])
    if last > e50 and e20 > e50:
        return "bull"
    if last < e50 and e20 < e50:
        return "bear"
    return "neutral"


def adjust_score(sig: Signal, regime: str, funding):
    """Ideas extra: filtro de régimen BTC y de funding (crowding)."""
    s = sig.score
    aligned = (sig.side == "long" and regime == "bull") or (sig.side == "short" and regime == "bear")
    counter = (sig.side == "long" and regime == "bear") or (sig.side == "short" and regime == "bull")
    if aligned:
        s += 8
        sig.reasons.append(f"A favor del régimen BTC ({regime})")
    elif counter and sig.setup != "Parabolic Short":
        s -= 12
        sig.reasons.append(f"Contra el régimen BTC ({regime})")
    if funding is not None:
        if sig.side == "long" and funding > 0.0008:
            s -= 6
            sig.reasons.append(f"Funding alto ({funding * 100:.3f}%): largos saturados")
        elif sig.side == "short" and funding < -0.0008:
            s -= 6
            sig.reasons.append(f"Funding muy negativo ({funding * 100:.3f}%): cortos saturados")
        elif sig.side == "long" and funding < -0.0005:
            s += 4
            sig.reasons.append("Funding negativo: combustible para squeeze")
    sig.score = max(0.0, min(100.0, s))
    return sig
