"""sozd.duma.gov.ru — законопроекты Государственной Думы.

Как это работает (замер 13.08.2026):
  * страница /oz принимает фильтр диапазона дат в параметре
    b[ExistsEventsDate] в формате «ДД.ММ.ГГГГ - ДД.ММ.ГГГГ»;
  * пагинация — обычный &page=N, по 10 записей на страницу;
  * весь контент отдаётся сервером в HTML — headless-браузер не нужен;
  * доступ только с российского IP: вне РФ соединение отбивается.

Фильтр проверен контролем: три разных периода дают три непересекающихся
диапазона номеров законопроектов, монотонных по времени.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..http import Fetcher
from ..models import Document

log = logging.getLogger(__name__)

BASE = "https://sozd.duma.gov.ru"
SEARCH = f"{BASE}/oz"
CONVOCATION = "8"  # текущий созыв

_DATE = re.compile(r"\b\d{2}\.\d{2}\.\d{4}\b")


def _parse_rows(html: str) -> list[Document]:
    soup = BeautifulSoup(html, "lxml")
    docs: list[Document] = []

    for item in soup.select("div.obj_item"):
        top = item.select_one("div.o_top")
        if not top:
            continue
        number = (top.get("data-law_number") or "").strip()
        link = top.select_one("a.o_num")
        if not number and link:
            number = link.get_text(strip=True)
        if not number:
            continue

        title_el = item.select_one("div.o_txt div.fw500")
        title = title_el.get_text(" ", strip=True) if title_el else ""
        txt_el = item.select_one("div.o_txt")
        if txt_el:
            full = txt_el.get_text(" ", strip=True)
            # хвост после наименования — уточнение «(в части ...)»
            if title and full.startswith(title):
                tail = full[len(title) :].strip()
                if tail:
                    title = f"{title} {tail}"

        # Даты и стадия лежат в соседних ячейках той же строки таблицы.
        row = item.find_parent("tr")
        dates: list[str] = []
        stage = ""
        if row:
            cells = row.find_all("td")
            for cell in cells:
                text = cell.get_text(" ", strip=True)
                found = _DATE.findall(text)
                if found and len(text) <= 40:
                    dates.extend(found)
                elif re.match(r"^\d+\.\d+\s", text) and not stage:
                    stage = text

        docs.append(
            Document(
                source="sozd.duma.gov.ru",
                doc_type="Законопроект",
                number=number,
                title=title,
                publication_date=dates[0] if dates else "",
                status_change_date=dates[-1] if dates else "",
                status=stage,
                department="Государственная Дума",
                url=f"{BASE}/bill/{number}",
            )
        )

    return docs


def collect(date_from: str, date_to: str, max_pages: int = 50) -> list[Document]:
    """Собрать законопроекты, по которым были события в заданном периоде."""
    fetcher = Fetcher("sozd")
    docs: list[Document] = []
    seen: set[str] = set()

    for page in range(1, max_pages + 1):
        params = {
            "b[ExistsEventsDate]": f"{date_from} - {date_to}",
            "b[Convocation][]": CONVOCATION,
        }
        if page > 1:
            params["page"] = str(page)

        resp = fetcher.get(SEARCH, params=params)
        batch = _parse_rows(resp.text)
        fresh = [d for d in batch if d.number not in seen]
        for d in fresh:
            seen.add(d.number)
        docs.extend(fresh)

        log.info("sozd: страница %s — %s записей (всего %s)", page, len(fresh), len(docs))

        if not fresh:
            break
        # последняя страница: пагинатор больше не предлагает следующую
        if f"page={page + 1}" not in resp.text:
            break

    return docs


def fetch_content(doc: Document, folder: Path) -> Path | None:
    """Вложения с карточки законопроекта; если их нет — HTML страницы."""
    from ..content import filename_from_url, looks_like_file, write_bytes

    if not doc.url:
        return None
    fetcher = Fetcher("sozd")
    resp = fetcher.get(doc.url)
    html_path = write_bytes(folder, "bill.html", resp.content)

    soup = BeautifulSoup(resp.text, "lxml")
    first: Path | None = None
    seen: set[str] = set()
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if not looks_like_file(href):
            continue
        full = urljoin(doc.url, href)
        host = urlparse(full).netloc.lower()
        if host and "duma.gov.ru" not in host:
            continue
        if full in seen:
            continue
        seen.add(full)
        try:
            blob = fetcher.get(full)
        except Exception as exc:  # noqa: BLE001
            log.warning("sozd вложение %s: %s", full, exc)
            continue
        if not blob.content:
            continue
        name = filename_from_url(full, "attachment")
        path = write_bytes(
            folder,
            name,
            blob.content,
            content_type=blob.headers.get("Content-Type", ""),
            content_disposition=blob.headers.get("Content-Disposition", ""),
        )
        if first is None:
            first = path
    return first or html_path
