from __future__ import annotations

import subprocess
import tkinter as tk
from tkinter import filedialog


def _create_root() -> tk.Tk:
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    root.update_idletasks()
    root.lift()
    root.focus_force()
    return root


def select_zip_files() -> list[str]:
    windows_result = _select_zip_files_windows()
    if windows_result is not None:
        return windows_result

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
    windows_result = _select_folder_windows(title)
    if windows_result is not None:
        return windows_result or None

    root = _create_root()
    try:
        selected = filedialog.askdirectory(title=title, parent=root, mustexist=False)
        return selected or None
    finally:
        root.destroy()


def _select_folder_windows(title: str) -> str | None:
    script = f"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = {title!r}
$dialog.ShowNewFolderButton = $true
$result = $dialog.ShowDialog()
if ($result -eq [System.Windows.Forms.DialogResult]::OK) {{
    [Console]::Write($dialog.SelectedPath)
}}
"""
    return _run_powershell_dialog(script)


def _select_zip_files_windows() -> list[str] | None:
    script = """
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Title = 'Select Snapchat export ZIP files'
$dialog.Filter = 'ZIP files (*.zip)|*.zip|All files (*.*)|*.*'
$dialog.Multiselect = $true
$dialog.CheckFileExists = $true
$result = $dialog.ShowDialog()
if ($result -eq [System.Windows.Forms.DialogResult]::OK) {
    [Console]::Write(($dialog.FileNames -join \"`n\"))
}
"""
    raw = _run_powershell_dialog(script)
    if raw is None:
        return None
    return [line for line in raw.splitlines() if line.strip()]


def _run_powershell_dialog(script: str) -> str | None:
    try:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-STA",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError:
        return None

    if completed.returncode != 0:
        return None

    return completed.stdout.strip()
