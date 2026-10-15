param(
    [string]$Config = "$PSScriptRoot\..\.deployment\customer.json",
    [ValidateSet("deploy", "preflight", "identities", "build", "plan", "apply", "models-verify", "sql-init", "verify")]
    [string]$Action = "deploy",
    [ValidateSet("prerequisites", "models", "platform", "edge-bootstrap", "candidate", "pilot", "ingestion")]
    [string]$Phase = "prerequisites",
    [string]$Approval = ""
)
$ErrorActionPreference = "Stop"
Push-Location (Join-Path $PSScriptRoot "..")
try {
    $arguments = @("-m", "scripts.deployment", "--config", $Config, $Action, "--phase", $Phase)
    if ($Approval) { $arguments += @("--approval", $Approval) }
    & python @arguments
    if ($LASTEXITCODE -ne 0) { throw "Deployment stopped. Resolve the reported prerequisite or failure before retrying." }
} finally {
    Pop-Location
}
