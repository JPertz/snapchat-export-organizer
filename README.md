# Snapchat Export Organizer

Windows app with a local browser UI for rebuilding Snapchat Memories exports into ready-to-import photos and videos with overlays and metadata.

## Goal

The app should let a user:

1. select multiple Snapchat export ZIP files and/or extracted export folders
2. merge `main` images and videos with matching `overlay` files
3. read metadata from Snapchat JSON files
4. write capture date and GPS data into exported media metadata
5. export finished JPG and MP4 files directly into one clean output folder

This repository contains the source code. End users should later download the ready-made Windows build from **GitHub Releases**, not the source ZIP from the main repository page.

## Why This Structure

The project is split into:

- a local browser UI built with React + Vite
- a Python processing pipeline that can also run without the UI
- a FastAPI backend that exposes local-only APIs on `127.0.0.1`
- build scripts for creating a standalone Windows `.exe`
- a GitHub Actions workflow for automatic Windows builds

That gives us two good paths:

- developers can work on the source code normally
- users can download a packaged Windows app without installing Python

## Planned User Flow

1. Open the app.
2. Add all Snapchat export ZIP files and/or extracted folders.
3. Choose an output folder.
4. Start processing.
5. Receive one folder that fills up with finished JPG and MP4 files while processing runs.

## Current Project Layout

```text
snapchat-export-organizer/
|-- .github/workflows/build-windows.yml
|-- scripts/build.ps1
|-- src/snapchat_export_organizer/
|   |-- app.py
|   |-- cli.py
|   |-- dialogs.py
|   |-- launcher.py
|   |-- models.py
|   |-- pipeline.py
|   |-- web.py
|   `-- __init__.py
|-- tests/
|-- webui/
|-- .gitignore
|-- pyproject.toml
`-- README.md
```

## Local Development

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .

cd webui
npm install
npm run build
cd ..

python -m snapchat_export_organizer.app
```

That starts the local FastAPI server, opens the default browser on `http://127.0.0.1:<port>`, and keeps all processing on the user's machine.

During processing, the app unpacks ZIP inputs only into an app-owned directory under the system temp folder. Finished JPG and MP4 files are staged in the chosen output folder and then atomically renamed into place. The app does not intentionally store Snapchat media inside the repository or in persistent app data folders. Only one app or CLI instance is allowed to run at a time.

## CLI Usage

The processing pipeline can also run without the browser UI:

```powershell
.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m snapchat_export_organizer.cli "C:\path\to\export.zip" --output "C:\path\to\output"
```

You can also use the installed console entry points:

```powershell
snapchat-export-organizer-app
snapchat-export-organizer "C:\path\to\export.zip" --output "C:\path\to\output"
```

The CLI writes finished JPG and MP4 files into the selected output folder. Just like the browser app, it uses only system-temp workspaces for temporary media handling and blocks parallel runs.

## Testing

For local test runs, install the development extras once:

```powershell
.venv\Scripts\Activate.ps1
python -m pip install -e .[dev]
python -m pytest tests\test_pipeline.py tests\test_web_api.py -q
```

For frontend development with the Vite dev server:

```powershell
.venv\Scripts\Activate.ps1
python -m pip install -e .

Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PWD'; python -m uvicorn snapchat_export_organizer.web:create_app --factory --host 127.0.0.1 --port 8000"

cd webui
npm install
npm run dev
```

The Vite config proxies `/api` requests to `http://127.0.0.1:8000`.

## Build A Windows App

```powershell
./scripts/build.ps1
```

The build script:

1. installs Python dependencies
2. installs frontend dependencies
3. builds the React app into the Python package
4. packages everything into a standalone Windows app with PyInstaller

The final app starts a local server and opens the browser automatically. End users do not need Python or Node.js installed.

## Release Strategy For End Users

If the goal is "download and use on Windows without installing Python", the best GitHub setup is:

1. keep this repository public
2. build a Windows executable in CI
3. publish the ZIP in GitHub Releases
4. tell users to download the release asset, not the source code archive

Recommended release assets later:

- `SnapchatExportOrganizer-win64.zip` for a portable version
- `SnapchatExportOrganizer-Setup.exe` if we later add an installer

With the current workflow, pushing a tag like `v0.1.0` is the intended release path for creating the downloadable Windows ZIP.

## API Overview

The local backend exposes these main endpoints:

- `GET /api/app-state`
- `POST /api/dialog/select-zips`
- `POST /api/dialog/select-folder`
- `POST /api/dialog/select-output`
- `POST /api/jobs`
- `GET /api/jobs/{job_id}`
- `GET /api/jobs/{job_id}/events`

All APIs bind only to `127.0.0.1`.

## Next Technical Steps

- improve JSON parsing against real Snapchat export samples
- preserve more metadata fields when available
- add drag and drop for ZIPs/folders
- add richer job history and export reports
- add CI coverage for frontend tests once the Node toolchain is installed in the project environment
