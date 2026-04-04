# Snapchat Export Organizer

Windows desktop app for rebuilding Snapchat Memories exports into ready-to-import photos with overlay and EXIF metadata.

## Goal

The app should let a user:

1. select multiple Snapchat export ZIP files and/or extracted export folders
2. merge `main` images with matching `overlay` images
3. read metadata from Snapchat JSON files
4. write capture date and GPS data into EXIF
5. export finished JPG files into one clean output folder

This repository contains the source code. End users should later download the ready-made Windows build from **GitHub Releases**, not the source ZIP from the main repository page.

## Why This Structure

The project is split into:

- a small desktop UI for Windows users
- a processing pipeline that can also run without the UI
- build scripts for creating a standalone `.exe`
- a GitHub Actions workflow for automatic Windows builds

That gives us two good paths:

- developers can work on the source code normally
- users can download a packaged Windows app without installing Python

## Planned User Flow

1. Open the app.
2. Add all Snapchat export ZIP files and/or extracted folders.
3. Choose an output folder.
4. Start processing.
5. Receive a folder with finished JPG files.

## Current Project Layout

```text
snapchat-export-organizer/
|-- .github/workflows/build-windows.yml
|-- scripts/build.ps1
|-- src/snapchat_export_organizer/
|   |-- app.py
|   |-- cli.py
|   |-- gui.py
|   |-- models.py
|   |-- pipeline.py
|   `-- __init__.py
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
python -m snapchat_export_organizer.app
```

## Build A Windows App

```powershell
./scripts/build.ps1
```

The build script uses PyInstaller and creates a standalone Windows app in `dist/`.

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

## Next Technical Steps

- improve JSON parsing against real Snapchat export samples
- preserve more metadata fields when available
- add drag and drop for ZIPs/folders
- add a nicer progress indicator and report
- add automated tests with sample fixtures
