param([string]$Terraform = "$PSScriptRoot\..\.tools\terraform.exe")
$ErrorActionPreference = "Stop"
$root = (Resolve-Path "$PSScriptRoot\..\..").Path
$tf = (Resolve-Path $Terraform).Path
foreach ($directory in @("infra\terraform", "infra\state")) {
    & $tf "-chdir=$root\$directory" fmt -check -recursive
    if ($LASTEXITCODE -ne 0) { throw "Terraform formatting failed: $directory" }
    & $tf "-chdir=$root\$directory" validate -no-color
    if ($LASTEXITCODE -ne 0) { throw "Terraform schema validation failed: $directory (run init -backend=false first)" }
    & $tf "-chdir=$root\$directory" test -no-color
    if ($LASTEXITCODE -ne 0) { throw "Mock-provider infrastructure checks failed: $directory" }
}
Push-Location $root
try {
    python gateway\tools\validate_bundle.py
    if ($LASTEXITCODE -ne 0) { throw "Disabled bundle checks failed" }
    python -m unittest discover -s tests\contract -p "test_gateway*.py" -v
    if ($LASTEXITCODE -ne 0) { throw "Gateway contracts failed" }
} finally {
    Pop-Location
}
Write-Output "Local evidence only: no Azure plan, deployment, connectivity or native capability proof."
