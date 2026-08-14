"""Окно выгрузки НПА. Точка входа .exe и `python -m npa_monitor gui`."""

from __future__ import annotations

import logging
import os
import sys
import threading
import tkinter as tk
from datetime import date, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from npa_monitor.paths import app_root, ensure_runtime_files, load_runtime_env
from npa_monitor.runner import CollectResult, DateError, run_collect, run_doctor

ACCENT = "#2F5496"
SOURCES = ("sozd", "cbr", "regulation")
SOURCE_LABELS = {
    "sozd": "sozd.duma.gov.ru",
    "cbr": "cbr.ru",
    "regulation": "regulation.gov.ru",
}


def _enable_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        from ctypes import windll

        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001
        try:
            from ctypes import windll

            windll.user32.SetProcessDPIAware()
        except Exception:  # noqa: BLE001
            pass


class TkLogHandler(logging.Handler):
    def __init__(self, append) -> None:
        super().__init__()
        self._append = append

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._append(self.format(record))
        except Exception:  # noqa: BLE001
            self.handleError(record)


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Правовой дайджест - сбор нормативных документов")
        self.minsize(720, 560)
        self.geometry("780x620")
        self._busy = False
        self._last_out: Path | None = None

        today = date.today()
        self.var_from = tk.StringVar(value=(today - timedelta(days=6)).strftime("%d.%m.%Y"))
        self.var_to = tk.StringVar(value=today.strftime("%d.%m.%Y"))
        self.var_out = tk.StringVar(value=str(app_root() / "out"))
        self.var_no_filter = tk.BooleanVar(value=False)
        self.var_no_content = tk.BooleanVar(value=False)
        self.var_sources = {name: tk.BooleanVar(value=True) for name in SOURCES}

        self._build()
        self._attach_logging()

    def _build(self) -> None:
        pad = {"padx": 12, "pady": 6}
        header = tk.Frame(self, bg=ACCENT)
        header.pack(fill=tk.X)
        tk.Label(
            header,
            text="Правовой дайджест",
            bg=ACCENT,
            fg="white",
            font=("Segoe UI", 14, "bold"),
        ).pack(anchor="w", padx=16, pady=(12, 0))
        tk.Label(
            header,
            text="cbr.ru  ·  sozd.duma.gov.ru  ·  regulation.gov.ru",
            bg=ACCENT,
            fg="#D6E3F8",
            font=("Segoe UI", 9),
        ).pack(anchor="w", padx=16, pady=(0, 12))

        body = ttk.Frame(self, padding=12)
        body.pack(fill=tk.BOTH, expand=True)

        period = ttk.LabelFrame(body, text="Период", padding=8)
        period.pack(fill=tk.X, **pad)
        ttk.Label(period, text="С").grid(row=0, column=0, padx=(0, 6))
        ttk.Entry(period, textvariable=self.var_from, width=14).grid(row=0, column=1)
        ttk.Label(period, text="По").grid(row=0, column=2, padx=(16, 6))
        ttk.Entry(period, textvariable=self.var_to, width=14).grid(row=0, column=3)
        ttk.Label(period, text="формат ДД.ММ.ГГГГ").grid(row=0, column=4, padx=(16, 0))

        src = ttk.LabelFrame(body, text="Источники", padding=8)
        src.pack(fill=tk.X, **pad)
        for i, name in enumerate(SOURCES):
            ttk.Checkbutton(src, text=SOURCE_LABELS[name], variable=self.var_sources[name]).grid(
                row=0, column=i, sticky="w", padx=(0, 18)
            )

        opts = ttk.LabelFrame(body, text="Выгрузка", padding=8)
        opts.pack(fill=tk.X, **pad)
        opts.columnconfigure(1, weight=1)
        ttk.Checkbutton(
            opts,
            text="Без тематического фильтра (выгрузить всё)",
            variable=self.var_no_filter,
        ).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Checkbutton(
            opts,
            text="Не скачивать содержание документов",
            variable=self.var_no_content,
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 6))
        ttk.Label(opts, text="Папка").grid(row=2, column=0, sticky="w", padx=(0, 6))
        ttk.Entry(opts, textvariable=self.var_out).grid(row=2, column=1, sticky="ew")
        ttk.Button(opts, text="Обзор…", command=self._browse_out).grid(row=2, column=2, padx=(8, 0))

        btns = ttk.Frame(body)
        btns.pack(fill=tk.X, **pad)
        self.btn_doctor = ttk.Button(btns, text="Проверить источники", command=self._start_doctor)
        self.btn_doctor.pack(side=tk.LEFT)
        self.btn_collect = ttk.Button(btns, text="Выгрузить", command=self._start_collect)
        self.btn_collect.pack(side=tk.LEFT, padx=(8, 0))
        self.btn_open = ttk.Button(btns, text="Открыть папку", command=self._open_out, state=tk.DISABLED)
        self.btn_open.pack(side=tk.LEFT, padx=(8, 0))

        log_frame = ttk.LabelFrame(body, text="Журнал", padding=4)
        log_frame.pack(fill=tk.BOTH, expand=True, **pad)
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        self.log_text = tk.Text(
            log_frame,
            wrap=tk.WORD,
            height=14,
            font=("Consolas", 9),
            state=tk.DISABLED,
            background="#F7F7F7",
        )
        scroll = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")

        self.status = ttk.Label(self, text="Готово", relief=tk.SUNKEN, anchor="w")
        self.status.pack(fill=tk.X, side=tk.BOTTOM, ipadx=8, ipady=4)

    def _attach_logging(self) -> None:
        handler = TkLogHandler(self.log)
        handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s %(message)s", "%H:%M:%S"))
        root_log = logging.getLogger()
        root_log.setLevel(logging.INFO)
        root_log.addHandler(handler)

    def _browse_out(self) -> None:
        chosen = filedialog.askdirectory(
            title="Папка выгрузки",
            initialdir=self.var_out.get() or str(app_root()),
        )
        if chosen:
            self.var_out.set(chosen)

    def _open_out(self) -> None:
        target = self._last_out or Path(self.var_out.get())
        if not target.exists():
            messagebox.showinfo("Папка выгрузки", "Папка ещё не создана — сначала выполните выгрузку.")
            return
        if sys.platform == "win32":
            os.startfile(target)  # noqa: S606 — открытие локальной папки по кнопке пользователя
        else:
            import subprocess

            subprocess.Popen(["xdg-open", str(target)])  # noqa: S603

    def log(self, message: str) -> None:
        def _append() -> None:
            self.log_text.configure(state=tk.NORMAL)
            if self.log_text.index("end-1c") != "1.0":
                self.log_text.insert(tk.END, "\n")
            self.log_text.insert(tk.END, message.rstrip("\n"))
            self.log_text.see(tk.END)
            self.log_text.configure(state=tk.DISABLED)

        self.after(0, _append)

    def _set_busy(self, busy: bool, status: str | None = None) -> None:
        self._busy = busy
        state = tk.DISABLED if busy else tk.NORMAL
        self.btn_doctor.configure(state=state)
        self.btn_collect.configure(state=state)
        if status is not None:
            self.status.configure(text=status)

    def _start_doctor(self) -> None:
        if self._busy:
            return
        self._set_busy(True, "Проверка источников…")
        threading.Thread(target=self._doctor_worker, daemon=True).start()

    def _doctor_worker(self) -> None:
        try:
            code = run_doctor(log=self.log)
            status = "Есть сбои маршрутов" if code else "Источники доступны"
        except Exception as exc:  # noqa: BLE001
            self.log(f"Сбой проверки: {exc}")
            status = "Ошибка проверки"
            code = 1
        self.after(0, lambda: self._doctor_done(code, status))

    def _doctor_done(self, code: int, status: str) -> None:
        self._set_busy(False, status)
        if code:
            messagebox.showwarning("Проверка источников", status)

    def _start_collect(self) -> None:
        if self._busy:
            return
        wanted = {name for name, var in self.var_sources.items() if var.get()}
        if not wanted:
            messagebox.showerror("Выгрузка", "Не выбран ни один источник.")
            return
        self._set_busy(True, "Идёт выгрузка…")
        date_from = self.var_from.get().strip()
        date_to = self.var_to.get().strip()
        out_dir = Path(self.var_out.get().strip() or (app_root() / "out"))
        no_filter = self.var_no_filter.get()
        no_content = self.var_no_content.get()
        threading.Thread(
            target=self._collect_worker,
            args=(date_from, date_to, wanted, out_dir, no_filter, no_content),
            daemon=True,
        ).start()

    def _collect_worker(
        self,
        date_from: str,
        date_to: str,
        wanted: set[str],
        out_dir: Path,
        no_filter: bool,
        no_content: bool,
    ) -> None:
        try:
            result = run_collect(
                date_from,
                date_to,
                sources=wanted,
                out_dir=out_dir,
                no_filter=no_filter,
                no_content=no_content,
                from_label="дата «с»",
                to_label="дата «по»",
                log=self.log,
            )
            self.after(0, lambda: self._collect_done(result, None))
        except (DateError, ValueError, OSError) as exc:
            self.log(str(exc))
            self.after(0, lambda: self._collect_done(None, str(exc)))
        except Exception as exc:  # noqa: BLE001
            self.log(f"Сбой выгрузки: {exc}")
            self.after(0, lambda: self._collect_done(None, f"Сбой выгрузки: {exc}"))

    def _collect_done(self, result: CollectResult | None, error: str | None) -> None:
        self._set_busy(False, "Ошибка выгрузки" if error else "Выгрузка готова")
        if error:
            messagebox.showerror("Выгрузка", error)
            return
        assert result is not None
        self._last_out = result.csv_path.parent
        self.btn_open.configure(state=tk.NORMAL)
        extra = ""
        if result.partial:
            extra = "\n\nregulation.gov.ru отдал только идентификаторы без наименований."
        messagebox.showinfo(
            "Выгрузка готова",
            f"Документов в выгрузке: {result.collected_count}\n\n"
            f"CSV:  {result.csv_path}\n"
            f"XLSX: {result.xlsx_path}"
            f"{extra}",
        )


def run_gui() -> int:
    _enable_dpi_awareness()
    ensure_runtime_files()
    load_runtime_env()
    app = App()
    app.mainloop()
    return 0


def main() -> int:
    return run_gui()


if __name__ == "__main__":
    # Замороженный exe и прямой запуск: пакет должен быть на PYTHONPATH (pathex=src).
    sys.exit(main())
