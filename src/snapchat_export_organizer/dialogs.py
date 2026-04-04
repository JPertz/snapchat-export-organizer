from __future__ import annotations

import tkinter as tk
from tkinter import filedialog


def _create_root() -> tk.Tk:
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    root.update_idletasks()
    return root


def select_zip_files() -> list[str]:
    root = _create_root()
    try:
        return list(
            filedialog.askopenfilenames(
                title="Select Snapchat export ZIP files",
                filetypes=[("ZIP files", "*.zip"), ("All files", "*.*")],
                parent=root,
            )
        )
    finally:
        root.destroy()


def select_folder(title: str) -> str | None:
    root = _create_root()
    try:
        selected = filedialog.askdirectory(title=title, parent=root)
        return selected or None
    finally:
        root.destroy()
