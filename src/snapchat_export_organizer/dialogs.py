from __future__ import annotations

import json
import queue
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol


_POWERSHELL_CANDIDATES = (
    Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"),
    Path(r"C:\Windows\Sysnative\WindowsPowerShell\v1.0\powershell.exe"),
)


class DialogProvider(Protocol):
    def select_zip_files(self) -> list[str]:
        ...

    def select_folder(self, title: str) -> str | None:
        ...


class PowerShellDialogProvider:
    def select_zip_files(self) -> list[str]:
        payload = _run_powershell_dialog(
            """
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Title = 'Select Snapchat export ZIP files'
$dialog.Filter = 'ZIP files (*.zip)|*.zip|All files (*.*)|*.*'
$dialog.Multiselect = $true
$dialog.CheckFileExists = $true
$result = $dialog.ShowDialog()
if ($result -eq [System.Windows.Forms.DialogResult]::OK) {
    @{
        status = 'ok'
        paths = $dialog.FileNames
    } | ConvertTo-Json -Compress
} else {
    @{
        status = 'cancel'
        paths = @()
    } | ConvertTo-Json -Compress
}
""",
            action_name="ZIP file picker",
        )
        return [str(item) for item in payload.get("paths", [])]

    def select_folder(self, title: str) -> str | None:
        payload = _run_powershell_dialog(
            f"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = {title!r}
$dialog.ShowNewFolderButton = $true
$result = $dialog.ShowDialog()
if ($result -eq [System.Windows.Forms.DialogResult]::OK) {{
    @{{
        status = 'ok'
        path = $dialog.SelectedPath
    }} | ConvertTo-Json -Compress
}} else {{
    @{{
        status = 'cancel'
        path = $null
    }} | ConvertTo-Json -Compress
}}
""",
            action_name="folder picker",
        )
        return str(payload["path"]) if payload.get("path") else None


@dataclass(slots=True)
class _DialogRequest:
    callback: Callable[[], object]
    event: threading.Event = field(default_factory=threading.Event)
    result: object | None = None
    error: RuntimeError | None = None


class NativeDialogService:
    def __init__(self) -> None:
        try:
            import tkinter as tk
            from tkinter import filedialog
        except Exception as exc:  # pragma: no cover - depends on local Tk install
            raise RuntimeError("Could not initialize the native Windows dialog service.") from exc

        self._owner_thread_id = threading.get_ident()
        self._requests: queue.Queue[_DialogRequest] = queue.Queue()
        self._closed = False
        self._lock = threading.Lock()
        self._tk = tk
        self._filedialog = filedialog
        self._root = tk.Tk()
        self._root.withdraw()
        self._root.update_idletasks()

    def select_zip_files(self) -> list[str]:
        return self._submit(self._select_zip_files_impl)

    def select_folder(self, title: str) -> str | None:
        return self._submit(lambda: self._select_folder_impl(title))

    def pump_events(self, timeout_seconds: float = 0.1) -> None:
        if self._closed:
            return
        self._pump_root()
        try:
            request = self._requests.get(timeout=timeout_seconds)
        except queue.Empty:
            return

        self._run_request(request)
        while True:
            try:
                request = self._requests.get_nowait()
            except queue.Empty:
                break
            self._run_request(request)
        self._pump_root()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        try:
            self._root.destroy()
        except self._tk.TclError:
            pass

    def _submit(self, callback: Callable[[], object]) -> Any:
        with self._lock:
            if self._closed:
                raise RuntimeError("The native Windows dialog service is no longer available.")

        if threading.get_ident() == self._owner_thread_id:
            return callback()

        request = _DialogRequest(callback=callback)
        self._requests.put(request)
        request.event.wait()
        if request.error is not None:
            raise request.error
        return request.result

    def _run_request(self, request: _DialogRequest) -> None:
        try:
            request.result = request.callback()
        except RuntimeError as exc:
            request.error = exc
        except Exception as exc:  # pragma: no cover - protects unexpected GUI failures
            request.error = RuntimeError(str(exc))
        finally:
            request.event.set()

    def _pump_root(self) -> None:
        try:
            self._root.update_idletasks()
            self._root.update()
        except self._tk.TclError:
            pass

    def _select_zip_files_impl(self) -> list[str]:
        self._prepare_dialog()
        try:
            paths = self._filedialog.askopenfilenames(
                parent=self._root,
                title="Select Snapchat export ZIP files",
                filetypes=(("ZIP files", "*.zip"), ("All files", "*.*")),
            )
        except self._tk.TclError as exc:
            raise RuntimeError("Could not open the ZIP file picker.") from exc
        finally:
            self._finish_dialog()
        return [str(Path(item)) for item in paths]

    def _select_folder_impl(self, title: str) -> str | None:
        self._prepare_dialog()
        try:
            selected = self._filedialog.askdirectory(parent=self._root, title=title, mustexist=False)
        except self._tk.TclError as exc:
            raise RuntimeError("Could not open the folder picker.") from exc
        finally:
            self._finish_dialog()
        return str(Path(selected)) if selected else None

    def _prepare_dialog(self) -> None:
        self._root.attributes("-topmost", True)
        self._root.lift()
        self._pump_root()

    def _finish_dialog(self) -> None:
        try:
            self._root.attributes("-topmost", False)
            self._root.withdraw()
            self._pump_root()
        except self._tk.TclError:
            pass


_DEFAULT_DIALOG_PROVIDER = PowerShellDialogProvider()


def default_dialog_provider() -> DialogProvider:
    return _DEFAULT_DIALOG_PROVIDER


def select_zip_files() -> list[str]:
    return default_dialog_provider().select_zip_files()


def select_folder(title: str) -> str | None:
    return default_dialog_provider().select_folder(title)


def _powershell_executable() -> str:
    for candidate in _POWERSHELL_CANDIDATES:
        if candidate.exists():
            return str(candidate)
    return "powershell"


def _run_powershell_dialog(script: str, *, action_name: str) -> dict[str, object]:
    wrapped_script = f"""
$ErrorActionPreference = 'Stop'
try {{
{script}
}} catch {{
    @{{
        status = 'error'
        message = $_.Exception.Message
    }} | ConvertTo-Json -Compress
    exit 1
}}
"""
    try:
        completed = subprocess.run(
            [
                _powershell_executable(),
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-STA",
                "-Command",
                wrapped_script,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        raise RuntimeError(f"Could not open the {action_name}.") from exc

    output = completed.stdout.strip()
    if not output:
        if completed.returncode == 0:
            return {"status": "cancel"}
        raise RuntimeError(f"Could not open the {action_name}.")

    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"The {action_name} returned an invalid response.") from exc

    if completed.returncode != 0 or payload.get("status") == "error":
        message = payload.get("message") or f"Could not open the {action_name}."
        raise RuntimeError(str(message))

    return payload
