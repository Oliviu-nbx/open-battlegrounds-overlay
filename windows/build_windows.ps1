# Builds a portable Windows application folder and ZIP on a Windows machine.
# Run from PowerShell: powershell -ExecutionPolicy Bypass -File .\windows\build_windows.ps1
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Dist = Join-Path $Root 'dist\windows'
$Build = Join-Path $Root '.work\windows-pyinstaller'
$Icon = Join-Path $Root 'assets\OpenBattlegroundsOverlay.ico'
$Cards = Join-Path $Root 'data\cards.json'

if (-not (Test-Path $Icon)) {
    throw "Missing Windows icon: $Icon"
}

$Python = Get-Command py -ErrorAction SilentlyContinue
if ($Python) {
    $PythonCommand = 'py'
    $PythonPrefix = @('-3')
} else {
    $PythonCommand = 'python'
    $PythonPrefix = @()
}

& $PythonCommand @PythonPrefix --version
& $PythonCommand @PythonPrefix -m pip install --upgrade pip
& $PythonCommand @PythonPrefix -m pip install -r (Join-Path $Root 'requirements.txt') pyinstaller

New-Item -ItemType Directory -Force -Path $Dist, $Build | Out-Null
$Arguments = @(
    '-m', 'PyInstaller', '--noconfirm', '--clean', '--windowed', '--onedir',
    '--name', 'OpenBattlegroundsOverlay', '--icon', $Icon,
    '--add-data', "$(Join-Path $Root 'assets');assets",
    '--distpath', $Dist, '--workpath', $Build, '--specpath', $Build,
    (Join-Path $Root 'main.py')
)
if (Test-Path $Cards) {
    $Arguments += @('--add-data', "$Cards;data")
} else {
    Write-Warning 'data\cards.json is absent. The app will obtain card metadata on its first online launch.'
}
& $PythonCommand @PythonPrefix @Arguments

$App = Join-Path $Dist 'OpenBattlegroundsOverlay'
$Zip = Join-Path $Dist 'OpenBattlegroundsOverlay-Windows.zip'
Remove-Item $Zip -Force -ErrorAction SilentlyContinue
Compress-Archive -Path $App -DestinationPath $Zip -CompressionLevel Optimal
Write-Host "Built portable app: $App"
Write-Host "Built release ZIP:    $Zip"
