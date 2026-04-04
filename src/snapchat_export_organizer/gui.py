from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .pipeline import process_sources


class OrganizerApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Snapchat Export Organizer")
        self.geometry("900x620")
        self.minsize(760, 520)

        self.sources: list[str] = []
        self.output_dir = tk.StringVar(value=str(Path.cwd() / "output"))
        self.status_text = tk.StringVar(value="Ready")
        self._worker_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._is_processing = False

        self._build_ui()
        self.after(150, self._poll_worker_queue)

    def _build_ui(self) -> None:
        container = ttk.Frame(self, padding=16)
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(3, weight=1)

        title = ttk.Label(
            container,
            text="Snapchat Export Organizer",
            font=("Segoe UI", 18, "bold"),
        )
        title.grid(row=0, column=0, sticky="w")

        subtitle = ttk.Label(
            container,
            text="Add Snapchat export ZIP files and folders, then build finished JPG files with overlay and metadata.",
            wraplength=800,
        )
        subtitle.grid(row=1, column=0, sticky="we", pady=(6, 18))

        controls = ttk.Frame(container)
        controls.grid(row=2, column=0, sticky="we", pady=(0, 12))
        for column in range(5):
            controls.columnconfigure(column, weight=1 if column == 4 else 0)

        self.add_zip_button = ttk.Button(controls, text="Add ZIP files", command=self._add_zip_files)
        self.add_zip_button.grid(row=0, column=0, padx=(0, 8))

        self.add_folder_button = ttk.Button(controls, text="Add folder", command=self._add_folder)
        self.add_folder_button.grid(row=0, column=1, padx=(0, 8))

        self.remove_button = ttk.Button(controls, text="Remove selected", command=self._remove_selected)
        self.remove_button.grid(row=0, column=2, padx=(0, 8))

        self.clear_button = ttk.Button(controls, text="Clear list", command=self._clear_sources)
        self.clear_button.grid(row=0, column=3, padx=(0, 8))

        self.start_button = ttk.Button(controls, text="Start processing", command=self._start_processing)
        self.start_button.grid(row=0, column=4, sticky="e")

        source_frame = ttk.LabelFrame(container, text="Selected inputs", padding=12)
        source_frame.grid(row=3, column=0, sticky="nsew", pady=(0, 12))
        source_frame.columnconfigure(0, weight=1)
        source_frame.rowconfigure(0, weight=1)

        self.source_list = tk.Listbox(source_frame, selectmode=tk.EXTENDED, height=10)
        self.source_list.grid(row=0, column=0, sticky="nsew")

        source_scroll = ttk.Scrollbar(source_frame, orient="vertical", command=self.source_list.yview)
        source_scroll.grid(row=0, column=1, sticky="ns")
        self.source_list.configure(yscrollcommand=source_scroll.set)

        output_frame = ttk.LabelFrame(container, text="Output", padding=12)
        output_frame.grid(row=4, column=0, sticky="we", pady=(0, 12))
        output_frame.columnconfigure(0, weight=1)

        output_entry = ttk.Entry(output_frame, textvariable=self.output_dir)
        output_entry.grid(row=0, column=0, sticky="we", padx=(0, 8))

        output_button = ttk.Button(output_frame, text="Choose output folder", command=self._choose_output_dir)
        output_button.grid(row=0, column=1)

        log_frame = ttk.LabelFrame(container, text="Log", padding=12)
        log_frame.grid(row=5, column=0, sticky="nsew", pady=(0, 12))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        container.rowconfigure(5, weight=1)

        self.log_widget = tk.Text(log_frame, height=12, wrap="word", state="disabled")
        self.log_widget.grid(row=0, column=0, sticky="nsew")

        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_widget.yview)
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log_widget.configure(yscrollcommand=log_scroll.set)

        footer = ttk.Frame(container)
        footer.grid(row=6, column=0, sticky="we")
        footer.columnconfigure(0, weight=1)

        ttk.Label(footer, textvariable=self.status_text).grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(footer, mode="indeterminate")
        self.progress.grid(row=0, column=1, sticky="e", padx=(12, 0))

    def _add_zip_files(self) -> None:
        file_paths = filedialog.askopenfilenames(
            title="Select Snapchat export ZIP files",
            filetypes=[("ZIP files", "*.zip"), ("All files", "*.*")],
        )
        for file_path in file_paths:
            self._append_source(file_path)

    def _add_folder(self) -> None:
        folder_path = filedialog.askdirectory(title="Select a Snapchat export folder")
        if folder_path:
            self._append_source(folder_path)

    def _append_source(self, value: str) -> None:
        normalized = str(Path(value))
        if normalized in self.sources:
            return
        self.sources.append(normalized)
        self.source_list.insert(tk.END, normalized)

    def _remove_selected(self) -> None:
        selected = list(self.source_list.curselection())
        for index in reversed(selected):
            self.source_list.delete(index)
            del self.sources[index]

    def _clear_sources(self) -> None:
        self.source_list.delete(0, tk.END)
        self.sources.clear()

    def _choose_output_dir(self) -> None:
        folder_path = filedialog.askdirectory(title="Select output folder")
        if folder_path:
            self.output_dir.set(folder_path)

    def _start_processing(self) -> None:
        if self._is_processing:
            return

        if not self.sources:
            messagebox.showwarning("Missing input", "Please add at least one ZIP file or folder.")
            return

        output_dir = self.output_dir.get().strip()
        if not output_dir:
            messagebox.showwarning("Missing output", "Please choose an output folder.")
            return

        self._set_processing(True)
        self._log("Processing started.")

        thread = threading.Thread(
            target=self._run_processing,
            args=(tuple(self.sources), output_dir),
            daemon=True,
        )
        thread.start()

    def _run_processing(self, sources: tuple[str, ...], output_dir: str) -> None:
        try:
            stats = process_sources(sources=sources, output_dir=output_dir, status=self._queue_log)
            self._worker_queue.put(("done", stats))
        except Exception as exc:
            self._worker_queue.put(("error", str(exc)))

    def _queue_log(self, message: str) -> None:
        self._worker_queue.put(("log", message))

    def _poll_worker_queue(self) -> None:
        try:
            while True:
                event_type, payload = self._worker_queue.get_nowait()
                if event_type == "log":
                    self._log(str(payload))
                elif event_type == "done":
                    stats = payload
                    self._set_processing(False)
                    self._log("Processing completed successfully.")
                    self.status_text.set(
                        f"Done. Merged: {stats.merged_files}, tagged: {stats.tagged_files}, errors: {len(stats.errors)}"
                    )
                    if stats.errors:
                        self._log("")
                        self._log("Errors:")
                        for item in stats.errors:
                            self._log(f"- {item}")
                    messagebox.showinfo(
                        "Finished",
                        "Processing finished.\n\n"
                        f"Merged files: {stats.merged_files}\n"
                        f"Tagged files: {stats.tagged_files}\n"
                        f"Errors: {len(stats.errors)}",
                    )
                elif event_type == "error":
                    self._set_processing(False)
                    self._log(f"Processing failed: {payload}")
                    self.status_text.set("Processing failed")
                    messagebox.showerror("Processing failed", str(payload))
        except queue.Empty:
            pass

        self.after(150, self._poll_worker_queue)

    def _set_processing(self, is_processing: bool) -> None:
        self._is_processing = is_processing
        state = "disabled" if is_processing else "normal"
        for button in (
            self.add_zip_button,
            self.add_folder_button,
            self.remove_button,
            self.clear_button,
            self.start_button,
        ):
            button.configure(state=state)

        if is_processing:
            self.status_text.set("Processing...")
            self.progress.start(12)
        else:
            self.progress.stop()

    def _log(self, message: str) -> None:
        self.log_widget.configure(state="normal")
        self.log_widget.insert(tk.END, message + "\n")
        self.log_widget.see(tk.END)
        self.log_widget.configure(state="disabled")


def run() -> None:
    app = OrganizerApp()
    app.mainloop()

