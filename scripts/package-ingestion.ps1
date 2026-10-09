$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Create .venv and install the root project first" }
& $python -m pip wheel --no-deps --wheel-dir services\usage-ingestion\wheels .
if ($LASTEXITCODE -ne 0) { throw "Ingestion wheel packaging failed" }
$catalogDirectory = Join-Path $root "services\usage-ingestion\gateway\catalog"
New-Item -ItemType Directory -Force -Path $catalogDirectory | Out-Null
Copy-Item -LiteralPath (Join-Path $root "gateway\catalog\models.json") -Destination $catalogDirectory
Write-Output "Deploy services\usage-ingestion from a private-network runner after reviewing configuration."
