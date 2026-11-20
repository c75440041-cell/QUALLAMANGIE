import numpy as np
import pandas as pd
import pytest

from config import Config
from state import State
from strategies import Signal, adjust_score, evaluate
from trader import Trader

CFG = Config(mode="paper")
H = 3_600_000
M15 = 900_000
DAY = 86_400_000
T0 = 1_700_006_400_000  # múltiplo de 1 día UTC (00:00)


def mk(ts, o, h, l, c, v):
    return pd.DataFrame({"ts": ts, "open": o, "high": h, "low": l, "close": c, "volume": v})


def daily_trend(n=60, g=1.008, rng=0.03):
    c = 1.0 * g ** np.arange(n)
    return mk(T0 + np.arange(n) * DAY, c, c * (1 + rng), c * (1 - rng), c, np.full(n, 1e6))


def hourly(n_pre=108, base=1.6, rng=0.01, consol=True):
    ts = T0 + np.arange(n_pre + 12) * H
    c = np.full(n_pre + 12, base)
    hi = c * (1 + rng / 2)
    lo = c * (1 - rng / 2)
    if consol:
        for k in range(12):
            hi[n_pre + k] = base * (1.004 - 0.0001 * k)
            lo[n_pre + k] = base * (0.996 + 0.0004 * k)
    return mk(ts, c, hi, lo, c, np.full(len(c), 1e4))


def m15(n=129, base=1.6, last_open=None, last_close=None, last_vol=400, vol=100):
    ts = T0 + np.arange(n) * M15
    c = np.full(n, base)
    o, h, l = c.copy(), c * 1.0007, c * 0.9993
    v = np.full(n, float(vol))
    o[-1], c[-1] = last_open, last_close
    h[-1], l[-1] = max(o[-1], c[-1]) * 1.0003, min(o[-1], c[-1]) * 0.9997
    v[-1] = last_vol
    return mk(ts, o, h, l, c, v)


def test_breakout_long_fires():
    d, h = daily_trend(), hourly()
    m = m15(last_open=1.6 * 1.002, last_close=1.6 * 1.0045)
    sigs = evaluate("TEST/USDT:USDT", d, h, m, CFG)
    s = [x for x in sigs if x.setup == "Breakout"]
    assert s and s[0].side == "long" and s[0].stop < s[0].entry
    assert s[0].score >= 55


def test_breakout_needs_volume():
    d, h = daily_trend(), hourly()
    m = m15(last_open=1.6 * 1.002, last_close=1.6 * 1.0045, last_vol=100)
    assert not [x for x in evaluate("T", d, h, m, CFG) if x.setup == "Breakout"]


def test_breakout_rejects_loose_consolidation():
    d, h = daily_trend(), hourly(consol=False, rng=0.12)   # velas de 12% de rango: nada tenso
    m = m15(last_open=1.6 * 1.002, last_close=1.6 * 1.0045)
    assert not [x for x in evaluate("T", d, h, m, CFG) if x.setup == "Breakout"]


def test_episodic_pivot_long():
    n = 60
    c = np.full(n, 1.0)
    d = mk(T0 + np.arange(n) * DAY, c, c * 1.03, c * 0.97, c, np.full(n, 1e6))
    h = hourly(base=1.0, rng=0.02, consol=False)
    m = m15(base=1.0, last_open=1.0, last_close=1.04, last_vol=900)
    s = [x for x in evaluate("T", d, h, m, CFG) if x.setup == "Episodic Pivot"]
    assert s and s[0].side == "long"


def test_parabolic_short():
    n = 60
    c = np.full(n, 1.0)
    c[-6:] = [1.0, 1.1, 1.2, 1.3, 1.45, 1.6]
    d = mk(T0 + np.arange(n) * DAY, c, c * 1.04, c * 0.97, c, np.full(n, 1e6))
    h = hourly(base=1.6, rng=0.03, consol=False)
    # 15m: la sesión de hoy termina a las 20:00 UTC
    nb = 129
    end = T0 + 20 * H
    ts = end - (nb - 1) * M15 + np.arange(nb) * M15
    cl = np.full(nb, 1.55)
    cl[-30:-2] = np.linspace(1.55, 1.64, 28)
    cl[-2] = 1.62
    cl[-1] = 1.55
    op = np.roll(cl, 1)
    op[0] = 1.55
    op[-1] = 1.61
    hi = np.maximum(op, cl) * 1.001
    lo = np.minimum(op, cl) * 0.999
    hi[-40] = 1.66   # máximo del día
    m = mk(ts, op, hi, lo, cl, np.full(nb, 100.0))
    s = [x for x in evaluate("T", d, h, m, CFG) if x.setup == "Parabolic Short"]
    assert s and s[0].side == "short" and s[0].stop > s[0].entry


def test_regime_adjustment():
    s = Signal("X", "long", "Breakout", 1.0, 0.98, 70.0, [])
    assert adjust_score(s, "bull", None).score > 70
    s = Signal("X", "long", "Breakout", 1.0, 0.98, 70.0, [])
    assert adjust_score(s, "bear", None).score < 70


class FakeEx:
    def __init__(self):
        self.price = {"TEST/USDT:USDT": 100.0}

    def amount_to_precision(self, s, q): return f"{q:.3f}"
    def price_to_precision(self, s, p): return f"{p:.4f}"
    def market(self, s): return {"limits": {"amount": {"min": 0.001}}}
    def fetch_ticker(self, s): return {"last": self.price[s]}
    def fetch_tickers(self, syms): return {s: {"last": self.price[s]} for s in syms}
    def fetch_ohlcv(self, *a, **k): raise RuntimeError("sin datos")


def make_trader(tmp_path):
    st = State(str(tmp_path), 1000.0)
    msgs = []
    return Trader(FakeEx(), CFG, st, msgs.append), st, msgs


def test_paper_lifecycle_tp1_then_breakeven(tmp_path):
    tr, st, msgs = make_trader(tmp_path)
    sig = Signal("TEST/USDT:USDT", "long", "Breakout", 100.0, 98.0, 80.0, [])
    ok, why = tr.open(sig)
    assert ok, why
    pos = st.data["positions"]["TEST/USDT:USDT"]
    # riesgo 0.5% de 1000 = $5 ; distancia 2 -> qty 2.5
    assert pos["qty"] == pytest.approx(2.5, rel=1e-3)
    tr.ex.price["TEST/USDT:USDT"] = 103.5          # 1.75R -> TP1
    tr.manage()
    pos = st.data["positions"]["TEST/USDT:USDT"]
    assert pos["tp1_hit"] and pos["qty"] == pytest.approx(1.25, rel=1e-3)
    assert pos["stop"] >= 100.0                     # break-even
    tr.ex.price["TEST/USDT:USDT"] = 99.0            # vuelve al stop
    tr.manage()
    assert "TEST/USDT:USDT" not in st.data["positions"]
    assert st.data["paper_equity"] > 1000.0         # cerró en positivo gracias al parcial


def test_paper_stop_loss_and_limits(tmp_path):
    tr, st, _ = make_trader(tmp_path)
    sig = Signal("TEST/USDT:USDT", "short", "Breakdown", 100.0, 102.0, 80.0, [])
    assert tr.open(sig)[0]
    assert not tr.open(sig)[0]                      # ya abierta
    tr.ex.price["TEST/USDT:USDT"] = 102.5
    tr.manage()
    assert not st.data["positions"]
    assert st.data["paper_equity"] < 1000.0
    st.data["paused"] = True
    assert not tr.can_open(sig)[0]
