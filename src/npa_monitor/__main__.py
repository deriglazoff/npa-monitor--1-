"""CLI: python -m npa_monitor collect|doctor

Примеры:
    python -m npa_monitor doctor
    python -m npa_monitor collect --from 29.06.2026 --to 05.07.2026
    python -m npa_monitor collect --from 01.08.2026 --to 07.08.2026 --sources sozd,cbr
    python -m npa_monitor collect --from 29.06.2026 --to 05.07.2026 --no-filter
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

from . import filters
from .export import to_csv, to_xlsx
from .models import Document
from .sources import REGISTRY

ROOT = Path(__file__).resolve().parents[2]
DATE_RE = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )


def _load_config(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _valid_date(value: str, label: str) -> str:
    if not DATE_RE.match(value):
        sys.exit(f"Ошибка: --{label} должен быть в формате ДД.ММ.ГГГГ, получено «{value}»")
    try:
        datetime.strptime(value, "%d.%m.%Y")
    except ValueError:
        sys.exit(f"Ошибка: --{label} не является существующей датой: «{value}»")
    return value


def cmd_doctor(args: argparse.Namespace) -> int:
    """Проверка маршрутов до каждого источника — запускать первой."""
    from .http import Fetcher, RouteError
    from .sources import regulation as reg

    checks = [
        ("sozd", "https://sozd.duma.gov.ru/oz"),
        ("cbr", "https://www.cbr.ru/news/"),
        ("regulation", "https://regulation.gov.ru/api/public/Projects?page=1&pageSize=1"),
    ]

    print("\nПроверка доступности источников\n" + "=" * 62)
    failed = 0
    for name, url in checks:
        try:
            fetcher = Fetcher(name)
            resp = fetcher.get(url)
            print(f"  [OK]    {name:<12} маршрут={fetcher.route:<7} {len(resp.content):>9} байт")
        except RouteError as exc:
            failed += 1
            print(f"  [СБОЙ]  {name:<12} {exc}")

    try:
        info = reg.probe()
        if info["with_content"] == 0:
            print(
                f"\n  ВНИМАНИЕ regulation.gov.ru: доступен (всего записей "
                f"{info['total_count']}), но содержательные поля пустые.\n  {info['note']}"
            )
    except Exception as exc:  # noqa: BLE001
        print(f"\n  regulation.gov.ru: диагностика не удалась — {exc}")

    print("=" * 62)
    if failed:
        print(
            "\nЕсли не отвечает sozd — проверьте PROXY_URL в .env: прокси выдан "
            "на 3 дня и мог истечь.\nПри запуске из России прокси не нужен: "
            "выставьте SOZD_ROUTE=direct.\n"
        )
    return 1 if failed else 0


def cmd_collect(args: argparse.Namespace) -> int:
    date_from = _valid_date(args.date_from, "from")
    date_to = _valid_date(args.date_to, "to")
    config = _load_config(Path(args.config))

    enabled = config.get("sources", {})
    if args.sources:
        wanted = {s.strip() for s in args.sources.split(",") if s.strip()}
    else:
        wanted = {name for name, on in enabled.items() if on}

    unknown = wanted - set(REGISTRY)
    if unknown:
        sys.exit(f"Неизвестные источники: {', '.join(sorted(unknown))}")

    max_pages = int(config.get("max_pages", 50))
    collected: list[Document] = []
    report: list[tuple[str, str, int, int]] = []

    for name in ("sozd", "cbr", "regulation"):
        if name not in wanted:
            continue
        print(f"\n→ {name}: сбор за {date_from} — {date_to}")
        try:
            docs = REGISTRY[name].collect(date_from, date_to, max_pages=max_pages)
        except Exception as exc:  # noqa: BLE001 — сбой источника не рушит прогон
            print(f"  СБОЙ: {exc}")
            report.append((name, "СБОЙ", 0, 0))
            continue

        raw = len(docs)
        if args.no_filter:
            kept = docs
        else:
            kept = filters.apply(docs, config.get("topics", {}))
        collected.extend(kept)

        status = "OK" if raw else "ПУСТО"
        if name == "regulation" and raw and not any(d.title for d in docs):
            status = "ЧАСТИЧНО"
        report.append((name, status, raw, len(kept)))
        print(f"  собрано {raw}, после фильтра {len(kept)}")

    stamp = f"{date_from.replace('.', '')}-{date_to.replace('.', '')}"
    out_dir = Path(args.out)
    csv_path = to_csv(collected, out_dir / f"npa_{stamp}.csv")
    xlsx_path = to_xlsx(collected, out_dir / f"npa_{stamp}.xlsx")

    print("\n" + "=" * 62)
    print(f"ИТОГ за период {date_from} — {date_to}")
    print("=" * 62)
    print(f"  {'источник':<20}{'статус':<12}{'собрано':>10}{'в выгрузке':>12}")
    for name, status, raw, kept in report:
        print(f"  {name:<20}{status:<12}{raw:>10}{kept:>12}")
    print(f"\n  ВСЕГО В ВЫГРУЗКЕ: {len(collected)}")
    print(f"  CSV:  {csv_path}")
    print(f"  XLSX: {xlsx_path}\n")

    if any(s == "ЧАСТИЧНО" for _, s, _, _ in report):
        print(
            "  ПРИМЕЧАНИЕ: regulation.gov.ru отдал только идентификаторы без\n"
            "  наименований — см. раздел «Ограничения» в README.md.\n"
        )
    return 0


def main() -> int:
    load_dotenv(ROOT / ".env")

    parser = argparse.ArgumentParser(
        prog="npa_monitor",
        description="Сбор нормативных документов с cbr.ru, sozd.duma.gov.ru, regulation.gov.ru",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="подробный лог")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="проверить доступность источников")
    doctor.set_defaults(func=cmd_doctor)

    collect = sub.add_parser("collect", help="собрать документы за период")
    collect.add_argument("--from", dest="date_from", required=True, help="ДД.ММ.ГГГГ")
    collect.add_argument("--to", dest="date_to", required=True, help="ДД.ММ.ГГГГ")
    collect.add_argument("--sources", help="через запятую: sozd,cbr,regulation")
    collect.add_argument("--config", default=str(ROOT / "config.yaml"))
    collect.add_argument("--out", default=str(ROOT / "out"))
    collect.add_argument(
        "--no-filter",
        action="store_true",
        help="выгрузить всё без тематического фильтра",
    )
    collect.set_defaults(func=cmd_collect)

    args = parser.parse_args()
    _setup_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
