"""Escanea todos los perpetuos USDT de BingX y devuelve señales ordenadas por score."""
from __future__ import annotations

import logging
import re

from indicators import rvol, to_df
from strategies import adjust_score, btc_regime, evaluate

BTC = "BTC/USDT:USDT"
log = logging.getLogger("scanner")


class Scanner:
    def __init__(self, ex, cfg):
        self.ex = ex
        self.cfg = cfg
        self.exclude = re.compile(cfg.exclude_regex) if cfg.exclude_regex else None

    def liquid_symbols(self):
        tickers = self.ex.fetch_tickers()
        out = []
        for sym, t in tickers.items():
            mk = self.ex.markets.get(sym)
            if not mk or not (mk.get("swap") and mk.get("linear") and mk.get("quote") == "USDT"):
                continue
            if mk.get("active") is False:
                continue
            if self.exclude and self.exclude.search(str(mk.get("id", "")).replace("-", "")):
                continue
            qv = float(t.get("quoteVolume") or 0)
            if qv < self.cfg.min_volume_usd:
                continue
            out.append((sym, qv, float(t.get("percentage") or 0)))
        out.sort(key=lambda x: x[1], reverse=True)
        return out[: self.cfg.max_symbols]

    def _df(self, sym, tf, limit):
        return to_df(self.ex.fetch_ohlcv(sym, tf, limit=limit))

    def funding(self, sym):
        try:
            return float(self.ex.fetch_funding_rate(sym).get("fundingRate"))
        except Exception:
            return None

    def scan(self):
        cfg = self.cfg
        universe = self.liquid_symbols()
        try:
            regime = btc_regime(self._df(BTC, "1h", 120).iloc[:-1])
        except Exception as e:
            log.warning("No se pudo calcular el régimen BTC: %s", e)
            regime = "neutral"

        signals, stage2 = [], 0
        for sym, _qv, pct in universe:
            try:
                m = self._df(sym, "15m", 130)
                if len(m) < 110:
                    continue
                m = m.iloc[:-1]                      # descarta la vela en curso
                # Prefiltro barato: solo analizamos a fondo lo que "se mueve" ahora mismo
                if rvol(m, 20) < cfg.prefilter_rvol and abs(pct) < cfg.prefilter_move24:
                    continue
                stage2 += 1
                h = self._df(sym, "1h", 120).iloc[:-1]
                d = self._df(sym, "1d", 60)
                for s in evaluate(sym, d, h, m, cfg):
                    adjust_score(s, regime, self.funding(sym))
                    signals.append(s)
            except Exception as e:                    # un símbolo roto no debe parar el escaneo
                log.debug("skip %s: %s", sym, e)
        signals.sort(key=lambda s: s.score, reverse=True)
        log.info("Escaneo: %d símbolos líquidos, %d analizados a fondo, %d señales | BTC %s",
                 len(universe), stage2, len(signals), regime)
        return signals, regime
