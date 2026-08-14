"""HTTP-слой с маршрутизацией на источник.

Ключевая особенность проекта: маршрут — свойство источника, а не глобальная
настройка. Замер 13.08.2026 показал, что sozd.duma.gov.ru доступен только через
RU-прокси, а cbr.ru и regulation.gov.ru через тот же прокси не отвечают вовсе
(датацентровый IP режется на их стороне). Поэтому каждый источник ходит своим
маршрутом, заданным в .env через <SOURCE>_ROUTE.
"""

from __future__ import annotations

import logging
import os
import time

import requests

log = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


class RouteError(RuntimeError):
    """Источник недоступен по заданному маршруту."""


class Fetcher:
    """Обёртка над requests с маршрутом, ретраями и паузой между запросами."""

    def __init__(self, source: str):
        self.source = source
        self.route = os.getenv(f"{source.upper()}_ROUTE", "direct").strip().lower()
        self.timeout = float(os.getenv("HTTP_TIMEOUT", "45"))
        self.delay = float(os.getenv("REQUEST_DELAY", "1.0"))
        self.retries = int(os.getenv("MAX_RETRIES", "3"))

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA, "Accept-Language": "ru-RU,ru"})

        if self.route == "proxy":
            proxy = os.getenv("PROXY_URL", "").strip()
            if not proxy:
                raise RouteError(
                    f"{source}: маршрут proxy, но PROXY_URL пуст. "
                    "Заполните .env или переключите на direct."
                )
            self.session.proxies = {"http": proxy, "https": proxy}

    def get(self, url: str, params: dict | None = None) -> requests.Response:
        return self._request("GET", url, params=params)

    def post(self, url: str, json: dict | None = None) -> requests.Response:
        return self._request("POST", url, json=json)

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        last: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                resp = self.session.request(method, url, timeout=self.timeout, **kwargs)
                resp.raise_for_status()
                time.sleep(self.delay)
                return resp
            except Exception as exc:  # noqa: BLE001 — на любой сбой одинаковая реакция
                last = exc
                log.warning(
                    "%s: попытка %s/%s не удалась (%s) — %s",
                    self.source,
                    attempt,
                    self.retries,
                    url,
                    exc,
                )
                time.sleep(self.delay * attempt)

        raise RouteError(
            f"{self.source}: {url} недоступен по маршруту '{self.route}' "
            f"после {self.retries} попыток. Последняя ошибка: {last}"
        )
