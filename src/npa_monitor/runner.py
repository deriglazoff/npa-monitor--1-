"""Общий прогон collect / doctor — и CLI, и GUI вызывают отсюда."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

from . import filters
from .export import to_csv, to_xlsx
from .models import Document
from .paths import app_root, resolve_config_file
from .sources import REGISTRY

DATE_RE = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")
SOURCE_ORDER = ("sozd", "cbr", "regulation")

LogFn = Callable[[str], None]


class DateError(ValueError):
    """Дата не в формате ДД.ММ.ГГГГ или не существует."""


@dataclass
class CollectResult:
    date_from: str
    date_to: str
    report: list[tuple[str, str, int, int]]
    collected_count: int
    csv_path: Path
    xlsx_path: Path
    partial: bool


def validate_date(value: str, label: str) -> str:
    if not DATE_RE.match(value):
        raise DateError(
            f"Ошибка: {label} должен быть в формате ДД.ММ.ГГГГ, получено «{value}»"
        )
    try:
        datetime.strptime(value, "%d.%m.%Y")
    except ValueError as exc:
        raise DateError(
            f"Ошибка: {label} не является существующей датой: «{value}»"
        ) from exc
    return value


def load_config(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data or {}


def run_doctor(*, log: LogFn = print) -> int:
    """Проверка маршрутов до каждого источника. 0 — все живы, 1 — есть сбои."""
    from .http import Fetcher, RouteError
    from .sources import regulation as reg

    checks = [
        ("sozd", "https://sozd.duma.gov.ru/oz"),
        ("cbr", "https://www.cbr.ru/news/"),
        ("regulation", "https://regulation.gov.ru/projects/"),
    ]

    log("\nПроверка доступности источников\n" + "=" * 62)
    failed = 0
    for name, url in checks:
        try:
            fetcher = Fetcher(name)
            resp = fetcher.get(url)
            log(f"  [OK]    {name:<12} маршрут={fetcher.route:<7} {len(resp.content):>9} байт")
        except RouteError as exc:
            failed += 1
            log(f"  [СБОЙ]  {name:<12} {exc}")

    try:
        info = reg.probe()
        if info["with_content"] == 0:
            log(
                f"\n  ВНИМАНИЕ regulation.gov.ru: доступен (всего записей "
                f"{info['total_count']}), но содержательные поля пустые.\n  {info['note']}"
            )
    except Exception as exc:  # noqa: BLE001
        log(f"\n  regulation.gov.ru: диагностика не удалась — {exc}")

    log("=" * 62)
    if failed:
        log(
            "\nЕсли не отвечает sozd — проверьте PROXY_URL в .env: прокси выдан "
            "на 3 дня и мог истечь.\nПри запуске из России прокси не нужен: "
            "выставьте SOZD_ROUTE=direct.\n"
        )
    return 1 if failed else 0


def run_collect(
    date_from: str,
    date_to: str,
    *,
    sources: set[str] | None = None,
    config_path: Path | None = None,
    out_dir: Path | None = None,
    no_filter: bool = False,
    no_content: bool = False,
    from_label: str = "--from",
    to_label: str = "--to",
    log: LogFn = print,
) -> CollectResult:
    date_from = validate_date(date_from, from_label)
    date_to = validate_date(date_to, to_label)

    root = app_root()
    config_path = resolve_config_file(Path(config_path) if config_path else None)
    out_dir = Path(out_dir) if out_dir else root / "out"
    config = load_config(config_path)

    enabled = config.get("sources", {})
    if sources is not None:
        wanted = {s.strip() for s in sources if s.strip()}
    else:
        wanted = {name for name, on in enabled.items() if on}

    if not wanted:
        raise ValueError("Не выбран ни один источник")

    unknown = wanted - set(REGISTRY)
    if unknown:
        raise ValueError(f"Неизвестные источники: {', '.join(sorted(unknown))}")

    max_pages = int(config.get("max_pages", 50))
    collected: list[Document] = []
    report: list[tuple[str, str, int, int]] = []

    for name in SOURCE_ORDER:
        if name not in wanted:
            continue
        log(f"\n-> {name}: сбор за {date_from} — {date_to}")
        try:
            docs = REGISTRY[name].collect(date_from, date_to, max_pages=max_pages)
        except Exception as exc:  # noqa: BLE001 — сбой источника не рушит прогон
            log(f"  СБОЙ: {exc}")
            report.append((name, "СБОЙ", 0, 0))
            continue

        raw = len(docs)
        if no_filter:
            kept = docs
        else:
            kept = filters.apply(docs, config.get("topics", {}))
        collected.extend(kept)

        status = "OK" if raw else "ПУСТО"
        if name == "regulation" and raw and not any(d.title for d in docs):
            status = "ЧАСТИЧНО"
        report.append((name, status, raw, len(kept)))
        log(f"  собрано {raw}, после фильтра {len(kept)}")

    stamp = f"{date_from.replace('.', '')}-{date_to.replace('.', '')}"
    if collected and not no_content:
        from .content import attach_content

        log(f"\n-> содержание: {len(collected)} карточек")
        n_files = attach_content(collected, out_dir, stamp, log)
        log(f"  сохранено файлов: {n_files}")
    csv_path = to_csv(collected, out_dir / f"npa_{stamp}.csv")
    xlsx_path = to_xlsx(collected, out_dir / f"npa_{stamp}.xlsx")
    partial = any(s == "ЧАСТИЧНО" for _, s, _, _ in report)

    log("\n" + "=" * 62)
    log(f"ИТОГ за период {date_from} — {date_to}")
    log("=" * 62)
    log(f"  {'источник':<20}{'статус':<12}{'собрано':>10}{'в выгрузке':>12}")
    for name, status, raw, kept in report:
        log(f"  {name:<20}{status:<12}{raw:>10}{kept:>12}")
    log(f"\n  ВСЕГО В ВЫГРУЗКЕ: {len(collected)}")
    log(f"  CSV:  {csv_path}")
    log(f"  XLSX: {xlsx_path}\n")

    if partial:
        log(
            "  ПРИМЕЧАНИЕ: regulation.gov.ru отдал только идентификаторы без\n"
            "  наименований — см. раздел «Ограничения» в README.md.\n"
        )

    return CollectResult(
        date_from=date_from,
        date_to=date_to,
        report=report,
        collected_count=len(collected),
        csv_path=csv_path,
        xlsx_path=xlsx_path,
        partial=partial,
    )
