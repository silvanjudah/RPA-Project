#!/usr/bin/env python3
"""Optional desktop front-end for the job bot ("robot tray" style).

The CLI is the primary interface; this window is a thin, thread-safe wrapper
around :class:`rpa_jobs.pipeline.JobBot` for users who prefer buttons over
terminal flags. It requires tkinter (bundled with most Python installs).
"""

from __future__ import annotations

import logging
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from tkinter import StringVar, filedialog, messagebox
import tkinter as tk
from tkinter import ttk

from rpa_jobs.config import load_config
from rpa_jobs.pipeline import JobBot, RunResult
from rpa_jobs.portals import PORTALS

LOG_COLOURS = {
    "DEBUG": "#8a8a8a",
    "INFO": "#d4d4d4",
    "WARNING": "#e5c07b",
    "ERROR": "#e06c75",
    "DONE": "#98c379",
    "PROGRESS": "#61afef",
}


class _QueueLogHandler(logging.Handler):
    def __init__(self, sink: "queue.Queue") -> None:
        super().__init__()
        self.sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.sink.put(("log", record.levelname, self.format(record)))
        except Exception:  # noqa: BLE001 - logging must never crash the app
            pass


class BotApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("RPA Job Vacancy Bot")
        self.geometry("920x660")
        self.minsize(780, 560)

        self._queue: queue.Queue = queue.Queue()
        self._running = False
        self._result: RunResult | None = None
        self._configure_logging()
        self._configure_styles()
        self._build_ui()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(120, self._poll_queue)

    # ------------------------------------------------------------------- setup
    def _configure_logging(self) -> None:
        logger = logging.getLogger("rpa.jobs")
        logger.setLevel(logging.INFO)
        logger.handlers.clear()
        handler = _QueueLogHandler(self._queue)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.propagate = False

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background="#f5f6fa")
        style.configure("TLabel", background="#f5f6fa", foreground="#202124")
        style.configure("Muted.TLabel", foreground="#5f6368")
        style.configure("Title.TLabel", font=("TkDefaultFont", 15, "bold"), foreground="#1f3864")
        style.configure("Accent.TButton", font=("TkDefaultFont", 10, "bold"))
        style.configure("TButton", padding=(10, 4))
        style.configure("TCheckbutton", background="#f5f6fa")

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=16)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x")
        ttk.Label(header, text="Job Vacancy Bot", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="Collect vacancies from a job portal and write a formatted Excel report.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(2, 10))

        form = ttk.Frame(outer)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)

        ttk.Label(form, text="Portal").grid(row=0, column=0, sticky="w", pady=4)
        default_portal = str(load_config().get("portal", "all"))
        self.portal_var = StringVar(value=default_portal)
        self.portal_box = ttk.Combobox(
            form,
            textvariable=self.portal_var,
            values=sorted(PORTALS),
            state="readonly",
            width=22,
        )
        self.portal_box.grid(row=0, column=1, sticky="w", padx=(8, 24), pady=4)
        self.portal_box.bind("<<ComboboxSelected>>", self._on_portal_change)

        self.portal_desc = ttk.Label(
            form, text=self._portal_label(default_portal), style="Muted.TLabel"
        )
        self.portal_desc.grid(row=0, column=2, columnspan=2, sticky="w", pady=4)

        ttk.Label(form, text="Max vacancies").grid(row=1, column=0, sticky="w", pady=4)
        self.limit_var = StringVar(value="50")
        ttk.Spinbox(form, from_=1, to=500, textvariable=self.limit_var, width=8).grid(
            row=1, column=1, sticky="w", padx=(8, 24), pady=4
        )

        self.details_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            form, text="Open detail pages (adds description, salary, skills)", variable=self.details_var
        ).grid(row=1, column=2, columnspan=2, sticky="w", pady=4)

        ttk.Label(form, text="Output folder").grid(row=2, column=0, sticky="w", pady=4)
        default_dir = str(load_config().get("output", {}).get("directory", "output"))
        self.folder_var = StringVar(value=default_dir)
        ttk.Entry(form, textvariable=self.folder_var).grid(
            row=2, column=1, columnspan=2, sticky="ew", padx=(8, 8), pady=4
        )
        ttk.Button(form, text="Browse…", command=self._choose_folder).grid(
            row=2, column=3, sticky="w", pady=4
        )

        self.append_var = tk.BooleanVar(value=False)
        ttk.Label(form, text="Keywords").grid(row=3, column=0, sticky="w", pady=4)
        self.keyword_var = StringVar(value="")
        ttk.Entry(form, textvariable=self.keyword_var).grid(
            row=3, column=1, columnspan=2, sticky="ew", padx=(8, 8), pady=4
        )
        ttk.Label(form, text="comma-separated, optional", style="Muted.TLabel").grid(
            row=3, column=3, sticky="w", pady=4
        )

        ttk.Label(form, text="Country").grid(row=4, column=0, sticky="w", pady=4)
        default_countries = load_config().get("filters", {}).get("countries", [])
        self.country_var = StringVar(value=", ".join(default_countries))
        ttk.Entry(form, textvariable=self.country_var).grid(
            row=4, column=1, columnspan=2, sticky="ew", padx=(8, 8), pady=4
        )
        ttk.Label(form, text="blank = worldwide", style="Muted.TLabel").grid(
            row=4, column=3, sticky="w", pady=4
        )

        ttk.Checkbutton(
            form,
            text="Append to the newest existing report and skip duplicates",
            variable=self.append_var,
        ).grid(row=5, column=1, columnspan=3, sticky="w", padx=(8, 0), pady=4)

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(14, 8))
        self.run_button = ttk.Button(
            actions, text="▶  Run robot", style="Accent.TButton", command=self._start_run
        )
        self.run_button.pack(side="left")
        self.open_button = ttk.Button(
            actions, text="Open Excel report", command=self._open_report, state="disabled"
        )
        self.open_button.pack(side="left", padx=8)
        self.status_var = StringVar(value="Idle — configure a run and press “Run robot”.")
        ttk.Label(actions, textvariable=self.status_var, style="Muted.TLabel").pack(
            side="left", padx=12
        )

        progress_row = ttk.Frame(outer)
        progress_row.pack(fill="x", pady=(0, 8))
        self.progress = ttk.Progressbar(progress_row, mode="determinate", maximum=100)
        self.progress.pack(fill="x")

        log_frame = ttk.Frame(outer)
        log_frame.pack(fill="both", expand=True)
        self.log = tk.Text(
            log_frame,
            bg="#1e1e1e",
            fg="#d4d4d4",
            insertbackground="#d4d4d4",
            relief="flat",
            wrap="word",
            font=("Menlo", 9),
            padx=10,
            pady=8,
            height=18,
        )
        scrollbar = ttk.Scrollbar(log_frame, command=self.log.yview)
        self.log.configure(yscrollcommand=scrollbar.set, state="disabled")
        self.log.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        for tag, colour in LOG_COLOURS.items():
            self.log.tag_configure(tag, foreground=colour)
        self.log.tag_configure("SUCCESS", foreground="#98c379")

        self._append_log(
            "INFO",
            "Ready. The default 'all' source aggregates live feeds: Arbeitnow, Jobicy, "
            "Remote OK, We Work Remotely and Python.org.",
        )

    # -------------------------------------------------------------------- events
    def _on_portal_change(self, _event=None) -> None:
        self.portal_desc.configure(text=self._portal_label(self.portal_var.get()))

    @staticmethod
    def _portal_label(name: str) -> str:
        portal_cls = PORTALS.get(name)
        return portal_cls.label if portal_cls else ""

    def _choose_folder(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.folder_var.get() or ".")
        if selected:
            self.folder_var.set(selected)

    def _start_run(self) -> None:
        if self._running:
            return
        try:
            limit = int(self.limit_var.get())
            if not 1 <= limit <= 500:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid limit", "Max vacancies must be a whole number from 1 to 500.")
            return

        folder = Path(self.folder_var.get().strip() or "output").expanduser().resolve()
        config = load_config()
        config["portal"] = self.portal_var.get()
        config.setdefault("crawl", {})["max_items"] = limit
        config["crawl"]["fetch_details"] = self.details_var.get()
        config.setdefault("output", {})["directory"] = str(folder)
        keywords = [
            part.strip()
            for part in self.keyword_var.get().replace(";", ",").split(",")
            if part.strip()
        ]
        config.setdefault("filters", {})["keywords"] = keywords
        countries = [
            part.strip()
            for part in self.country_var.get().replace(";", ",").split(",")
            if part.strip()
        ]
        config["filters"]["countries"] = countries

        self._clear_log()
        self._result = None
        self._running = True
        self.run_button.configure(state="disabled")
        self.open_button.configure(state="disabled")
        self.progress.configure(value=0)
        self.status_var.set("Robot running…")

        worker = threading.Thread(
            target=self._run_bot,
            args=(config, self.append_var.get()),
            daemon=True,
        )
        worker.start()

    def _run_bot(self, config: dict, append: bool) -> None:
        try:
            bot = JobBot(config, progress=self._on_progress, append=append)
            result = bot.run()
        except Exception as exc:  # noqa: BLE001 - surface any failure in the UI
            self._queue.put(("error", f"{type(exc).__name__}: {exc}"))
            return
        self._queue.put(("done", result))

    # Runs on the Tk main thread via _poll_queue.
    def _on_progress(self, index: int, total: int, title: str) -> None:
        self._queue.put(("progress", index, total, title))

    def _poll_queue(self) -> None:
        try:
            while True:
                message = self._queue.get_nowait()
                kind = message[0]
                if kind == "log":
                    self._append_log(message[1], message[2])
                elif kind == "progress":
                    _kind, index, total, title = message
                    self.progress.configure(maximum=max(total, 1), value=index)
                    self.status_var.set(f"Processing {index}/{total}: {_cut(title, 52)}")
                elif kind == "done":
                    self._on_done(message[1])
                elif kind == "error":
                    self._on_error(message[1])
        except queue.Empty:
            pass
        finally:
            self.after(120, self._poll_queue)

    def _on_done(self, result: RunResult) -> None:
        self._running = False
        self._result = result
        self.run_button.configure(state="normal")
        self.open_button.configure(state="normal")
        self.progress.configure(value=self.progress.cget("maximum"))
        self.status_var.set(
            f"Done — {result.successful} new, {result.skipped} duplicates, "
            f"{result.filtered} filtered, {result.failed} failed · {len(result.jobs)} rows"
        )
        self._append_log("SUCCESS", "")
        self._append_log(
            "SUCCESS",
            f"Report written: {result.output_path}  ({result.duration_seconds:.1f}s)",
        )

    def _on_error(self, message: str) -> None:
        self._running = False
        self.run_button.configure(state="normal")
        self.progress.configure(value=0)
        self.status_var.set("Run failed — see the log.")
        self._append_log("ERROR", message)

    def _open_report(self) -> None:
        if not self._result or not self._result.output_path:
            return
        path = str(self._result.output_path)
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Could not open report", f"{exc}\n\nReport: {path}")

    def _append_log(self, level: str, message: str) -> None:
        tag = level if level in LOG_COLOURS else ("ERROR" if level == "WARNING" else "INFO")
        self.log.configure(state="normal")
        self.log.insert("end", message + "\n", tag)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.progress.configure(value=0)

    def _on_close(self) -> None:
        if self._running and not messagebox.askyesno(
            "Robot is running", "A collection run is still in progress. Quit anyway?"
        ):
            return
        self.destroy()


def _cut(value: str, width: int) -> str:
    text = value or ""
    return text if len(text) <= width else text[: width - 1] + "…"


def main() -> int:
    app = BotApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
