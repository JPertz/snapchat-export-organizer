$ErrorActionPreference = "Stop"

python -m pip install --upgrade pip
python -m pip install -e .
python -m pip install pyinstaller
npm install --prefix webui
npm run build --prefix webui

python -m PyInstaller `
  --noconfirm `
  --clean `
  --windowed `
  --name SnapchatExportOrganizer `
  --collect-data snapchat_export_organizer `
  --paths src `
  src/snapchat_export_organizer/app.py

if (Test-Path "dist\SnapchatExportOrganizer-win64.zip") {
  Remove-Item -LiteralPath "dist\SnapchatExportOrganizer-win64.zip"
}

Compress-Archive `
  -Path "dist\SnapchatExportOrganizer\*" `
  -DestinationPath "dist\SnapchatExportOrganizer-win64.zip"

Write-Host ""
Write-Host "Build completed."
Write-Host "Portable app: dist/SnapchatExportOrganizer/"
Write-Host "ZIP package:  dist/SnapchatExportOrganizer-win64.zip"
