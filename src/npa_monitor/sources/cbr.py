"""cbr.ru — Банк России.

Как это работает (замер 13.08.2026):
  * раздел /news/ не содержит новостей в HTML — они рендерятся на клиенте.
    Реальные источники данных найдены в inline-скрипте страницы. Лент ДВЕ,
    и они дополняют друг друга — сбор только одной даёт пробелы:
        GET /news/eventandpress/?page=N&IsEng=false&type=100
            &dateFrom=&dateTo=&Tid=&vol=&phrase=&pagesize=20
        GET /news/new_ent/?page=N&IsEng=false
            &dateFrom=&dateTo=&Tid=&phrase=&pagesize=20
    Первая — события, пресс-релизы и интервью; вторая — новости и
    аналитические материалы. Обе отдают JSON: name_doc, DT (дата),
    doc_htm (id), TBLType (events | press | interview).
    Проверено: на 13.08.2026 первая лента обрывалась на 27.07, вторая
    содержала материалы по 12.08 — то есть по одной ленте свежая неделя
    выглядела бы пустой.
  * ВАЖНО: параметры dateFrom/dateTo сервером игнорируются — проверено на
    трёх периодах, ответ всегда с текущей ленты. Поэтому период применяется
    НА НАШЕЙ СТОРОНЕ: лента пагинируется вглубь, пока даты не уйдут раньше
    начала периода. Так надёжнее и не зависит от их серверного фильтра.
  * Пропуск неполного набора параметров даёт {"Error":"Error loading data."} —
    нужны все ключи, включая пустые Tid, vol, phrase.
  * дополнительно снимается витрина /project_na/ (проекты НПА на публичном
    обсуждении) — она показывает только текущее окно обсуждения.

Доступ прямой. Через датацентровый RU-прокси сайт не отвечает — учтено
маршрутом CBR_ROUTE=direct в .env.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..http import Fetcher
from ..models import Document

log = logging.getLogger(__name__)

BASE = "https://www.cbr.ru"
PROJECT_NA = f"{BASE}/project_na/"

FEED_TYPE = 100  # вкладка «Все» — единственная непустая у eventandpress
PAGE_SIZE = 20

# Две ленты портала. Ключи параметров различаются: у new_ent нет type и vol.
FEEDS = [
    (
        f"{BASE}/news/eventandpress/",
        {"IsEng": "false", "type": str(FEED_TYPE), "dateFrom": "", "dateTo": "", "Tid": "", "vol": "", "phrase": ""},
    ),
    (
        f"{BASE}/news/new_ent/",
        {"IsEng": "false", "dateFrom": "", "dateTo": "", "Tid": "", "phrase": ""},
    ),
]

_DATE = re.compile(r"\b(\d{2}\.\d{2}\.\d{4})\b")

_TYPE_MARKERS = [
    ("указание", "Указание"),
    ("положение", "Положение"),
    ("информационное письмо", "Информационное письмо"),
    ("методическ", "Методические рекомендации"),
    ("инструкц", "Инструкция"),
    ("проект", "Проект нормативного акта"),
    ("приказ", "Приказ"),
]

_TBL_LABELS = {
    "press": "Пресс-релиз",
    "events": "Событие / материал",
    "interview": "Интервью",
}


def _guess_type(title: str, tbl_type: str) -> str:
    low = title.lower()
    for marker, label in _TYPE_MARKERS:
        if marker in low:
            return label
    return _TBL_LABELS.get(tbl_type, "Материал Банка России")


def _parse_dt(value: str) -> datetime | None:
    """ISO-дата из ленты («2026-07-27T00:00:00») → datetime."""
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d")
    except ValueError:
        return None


def _collect_feed(
    fetcher: Fetcher,
    url: str,
    base_params: dict,
    lo: datetime,
    hi: datetime,
    max_pages: int,
    seen: set[str],
) -> list[Document]:
    docs: list[Document] = []
    label = url.rstrip("/").rsplit("/", 1)[-1]

    for page in range(1, max_pages + 1):
        params = {**base_params, "page": str(page), "pagesize": str(PAGE_SIZE)}
        resp = fetcher.get(url, params=params)
        try:
            batch = resp.json()
        except ValueError:
            log.warning("cbr/%s: страница %s вернула не-JSON, останавливаюсь", label, page)
            break

        if not isinstance(batch, list) or not batch:
            break

        dates = [_parse_dt(row.get("DT", "")) for row in batch]
        in_period = 0

        for row, dt in zip(batch, dates):
            if dt is None or not (lo <= dt <= hi):
                continue
            doc_id = str(row.get("doc_htm") or "").strip()
            title = (row.get("name_doc") or "").strip()
            if not title:
                continue
            url = f"{BASE}/press/event/?id={doc_id}" if doc_id else f"{BASE}/news/"
            if url in seen:
                continue
            seen.add(url)
            in_period += 1

            docs.append(
                Document(
                    source="cbr.ru",
                    doc_type=_guess_type(title, str(row.get("TBLType", ""))),
                    number=doc_id,
                    title=title,
                    publication_date=dt.strftime("%d.%m.%Y"),
                    status_change_date=dt.strftime("%d.%m.%Y"),
                    status="Опубликовано",
                    department="Банк России",
                    url=url,
                )
            )

        oldest = min((d for d in dates if d), default=None)
        log.info(
            "cbr/%s: страница %s — в периоде %s (всего %s), самая ранняя %s",
            label,
            page,
            in_period,
            len(docs),
            oldest.strftime("%d.%m.%Y") if oldest else "—",
        )

        # Лента отсортирована по убыванию даты: как только вся страница
        # оказалась раньше начала периода — глубже идти незачем.
        if oldest and oldest < lo:
            break

    return docs


def _parse_project_na(html: str) -> list[Document]:
    soup = BeautifulSoup(html, "lxml")
    docs: list[Document] = []

    for link in soup.find_all("a", href=True):
        title = link.get_text(" ", strip=True)
        if len(title) < 25:
            continue
        href = link["href"]
        if not any(m in href for m in ("/Queries/", "/StaticHtml/", "/na/", "/analytics/")):
            continue

        block = link.find_parent(["div", "li", "tr"]) or link
        found = _DATE.findall(block.get_text(" ", strip=True))

        docs.append(
            Document(
                source="cbr.ru",
                doc_type="Проект нормативного акта",
                title=title,
                publication_date=found[0] if found else "",
                status_change_date=found[-1] if found else "",
                status="Публичное обсуждение",
                department="Банк России",
                url=urljoin(BASE, href),
            )
        )

    return docs


def collect(date_from: str, date_to: str, max_pages: int = 50) -> list[Document]:
    fetcher = Fetcher("cbr")
    lo = datetime.strptime(date_from, "%d.%m.%Y")
    hi = datetime.strptime(date_to, "%d.%m.%Y")

    seen: set[str] = set()
    docs: list[Document] = []
    for url, base_params in FEEDS:
        docs.extend(_collect_feed(fetcher, url, base_params, lo, hi, max_pages, seen))

    # Витрина текущих обсуждений: для прошедшего периода обычно пустая,
    # для регулярного режима — основной источник проектов НПА.
    try:
        resp = fetcher.get(PROJECT_NA)
        for doc in _parse_project_na(resp.text):
            if doc.url in seen or not doc.publication_date:
                continue
            dt = None
            try:
                dt = datetime.strptime(doc.publication_date, "%d.%m.%Y")
            except ValueError:
                pass
            if dt and lo <= dt <= hi:
                seen.add(doc.url)
                docs.append(doc)
    except Exception as exc:  # noqa: BLE001 — витрина не критична для выгрузки
        log.warning("cbr/project_na недоступен: %s", exc)

    return docs
