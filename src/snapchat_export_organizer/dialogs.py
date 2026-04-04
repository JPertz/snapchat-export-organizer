from __future__ import annotations

import json
import subprocess
from pathlib import Path


_POWERSHELL_CANDIDATES = (
    Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"),
    Path(r"C:\Windows\Sysnative\WindowsPowerShell\v1.0\powershell.exe"),
)


def select_zip_files() -> list[str]:
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


def select_folder(title: str) -> str | None:
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
