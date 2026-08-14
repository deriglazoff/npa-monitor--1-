"""CLI: python -m npa_monitor collect|doctor|gui

Примеры:
    python -m npa_monitor doctor
    python -m npa_monitor collect --from 29.06.2026 --to 05.07.2026
    python -m npa_monitor collect --from 01.08.2026 --to 07.08.2026 --sources sozd,cbr
    python -m npa_monitor collect --from 29.06.2026 --to 05.07.2026 --no-filter
    python -m npa_monitor gui
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .paths import app_root, ensure_runtime_files, load_runtime_env
from .runner import DateError, run_collect, run_doctor


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )


def cmd_doctor(_args: argparse.Namespace) -> int:
    return run_doctor(log=print)


def cmd_collect(args: argparse.Namespace) -> int:
    wanted = None
    if args.sources:
        wanted = {s.strip() for s in args.sources.split(",") if s.strip()}
    try:
        run_collect(
            args.date_from,
            args.date_to,
            sources=wanted,
            config_path=Path(args.config),
            out_dir=Path(args.out),
            no_filter=args.no_filter,
            no_content=args.no_content,
            log=print,
        )
    except (DateError, ValueError, FileNotFoundError) as exc:
        sys.exit(str(exc))
    return 0


def cmd_gui(_args: argparse.Namespace) -> int:
    from .gui import run_gui

    return run_gui()


def main() -> int:
    ensure_runtime_files()
    load_runtime_env()
    root = app_root()

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
    collect.add_argument("--config", default=str(root / "config.yaml"))
    collect.add_argument("--out", default=str(root / "out"))
    collect.add_argument(
        "--no-filter",
        action="store_true",
        help="выгрузить всё без тематического фильтра",
    )
    collect.add_argument(
        "--no-content",
        action="store_true",
        help="не скачивать содержание документов",
    )
    collect.set_defaults(func=cmd_collect)

    gui = sub.add_parser("gui", help="открыть окно выгрузки")
    gui.set_defaults(func=cmd_gui)

    args = parser.parse_args()
    _setup_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
