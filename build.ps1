# Build a lean onefile GUI exe (stdlib + tkinter only).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

python -m PyInstaller --noconfirm --clean hikvision-channel-order.spec
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$exe = Join-Path $PSScriptRoot "dist\HikvisionChannelOrder.exe"
if (-not (Test-Path $exe)) {
    Write-Error "Build finished but exe not found: $exe"
}
$sizeMb = [math]::Round((Get-Item $exe).Length / 1MB, 2)
Write-Host "OK: $exe ($sizeMb MB)"
