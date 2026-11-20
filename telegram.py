from __future__ import annotations

import logging
import time

import requests

log = logging.getLogger("telegram")


class Notifier:
    def __init__(self, cfg):
        self.token = cfg.tg_token
        self.chat = cfg.tg_chat_id
        self.base = f"https://api.telegram.org/bot{self.token}"
        self._last_alert = {}

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat)

    def send(self, text: str):
        log.info(text.replace("\n", " | "))
        if not self.enabled:
            return
        try:
            r = requests.post(
                f"{self.base}/sendMessage",
                json={"chat_id": self.chat, "text": text, "parse_mode": "HTML",
                      "disable_web_page_preview": True},
                timeout=15,
            )
            if r.status_code != 200:
                log.warning("Telegram respondió %s: %s", r.status_code, r.text[:200])
        except Exception as e:
            log.warning("Telegram error: %s", e)

    def alert_once(self, key: str, text: str, every: int = 1800):
        """Evita spamear el mismo error."""
        now = time.time()
        if now - self._last_alert.get(key, 0) >= every:
            self._last_alert[key] = now
            self.send(text)

    def listen(self, handlers: dict, stop):
        """Comandos de Telegram por long-polling. Solo responde al chat autorizado."""
        if not self.enabled:
            return
        offset = None
        while not stop.is_set():
            try:
                r = requests.get(f"{self.base}/getUpdates",
                                 params={"timeout": 25, "offset": offset}, timeout=35).json()
                for u in r.get("result", []):
                    offset = u["update_id"] + 1
                    msg = u.get("message") or {}
                    if str(msg.get("chat", {}).get("id")) != str(self.chat):
                        continue
                    parts = (msg.get("text") or "").split()
                    if not parts:
                        continue
                    fn = handlers.get(parts[0].split("@")[0].lower())
                    if fn:
                        self.send(fn())
            except Exception as e:
                log.debug("poll error: %s", e)
                stop.wait(5)
