# One command: set up (first time only), check .env, run the tests, then run the portal.
# Usage: powershell -ExecutionPolicy Bypass -File .\scripts\go.ps1 [-SkipTests] [-DeadSession] [-Inputs inputs\invoice_changed.json] [-FailAt login] [-CodeSource totp]
param([switch]$SkipTests, [switch]$DeadSession, [string]$Inputs = "inputs\invoice.json", [string]$FailAt = "", [string]$CodeSource = "totp")
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$py = "python"
if (-not (Get-Command $py -ErrorAction SilentlyContinue)) { Write-Host "Python 3.9+ is required (python not found)."; exit 1 }
& $py -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)"
if ($LASTEXITCODE -ne 0) { Write-Host "Python 3.9+ is required."; exit 1 }

$vpy = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $vpy)) { & $py -m venv .venv; if ($LASTEXITCODE -ne 0) { exit 1 } }
if (-not (Test-Path ".venv\.deps-ok")) {
  & $vpy -m pip install --quiet --upgrade pip
  & $vpy -m pip install --quiet -r requirements.txt
  if ($LASTEXITCODE -ne 0) { Write-Host "Dependency install failed."; exit 1 }
  if (-not $env:PW_CHANNEL) { & $vpy -m playwright install chromium; if ($LASTEXITCODE -ne 0) { exit 1 } }
  New-Item -ItemType File -Path ".venv\.deps-ok" -Force | Out-Null
}

if (-not (Test-Path ".env")) { Copy-Item .env.example .env; Write-Host "Created .env. Fill in the values (it is git-ignored), then run this again."; exit 1 }

$need = @("PORTAL_EMAIL", "PORTAL_PASSWORD", "ZOHO_ORG_ID")
if ($CodeSource -eq "totp") { $need += "PORTAL_TOTP_SECRET" }
$missing = @()
foreach ($k in $need) {
  $line = Get-Content .env | Where-Object { $_ -match "^$k=" } | Select-Object -First 1
  $val = if ($line) { ($line -split "=", 2)[1].Trim() } else { "" }
  if (-not $val) { $missing += $k }
}
if ($missing.Count -gt 0) { Write-Host ("Fill these in .env, then run again: " + ($missing -join ", ")); exit 1 }

if (-not $SkipTests) { & $vpy -m pytest -q; if ($LASTEXITCODE -ne 0) { Write-Host "Tests failed."; exit 1 } }

if ($DeadSession) {
  # Evaluation only: keep a backup of the saved session, break its cookies, then run normally.
  & $vpy -m portal_runner kill-session --state .state\session.json
  if ($LASTEXITCODE -ne 0) { exit 1 }
}

$a = @("-m", "portal_runner", "run", "--inputs", $Inputs, "--code-source", $CodeSource)
if ($FailAt) { $a += @("--fail-at", $FailAt) }
$runStart = Get-Date
& $vpy @a
$runCode = $LASTEXITCODE
if ($DeadSession -or $Inputs -ne "inputs\invoice.json") { & $vpy -m portal_runner last-run --out outputs }
if ($FailAt -and $runCode -ne 0) {
  # Only a failure at the stage we asked for, made by the forced-failure hook, counts as expected.
  # Anything else falls through to the normal "Run failed" exit.
  $b = Get-ChildItem outputs -Directory -Filter "failure-*" | Where-Object { $_.LastWriteTime -ge $runStart } | Sort-Object LastWriteTime | Select-Object -Last 1
  if ($b) {
    $st = (Get-Content (Join-Path $b.FullName "stage.txt") -Raw).Trim()
    $er = Get-Content (Join-Path $b.FullName "error.txt") -Raw
    if (($st -eq $FailAt) -and ($er -match "forced failure for evidence demo")) {
      $z = Join-Path "outputs" ($b.Name + ".zip")
      Compress-Archive -Path $b.FullName -DestinationPath $z -Force
      Write-Host ("Expected failure at stage " + $st + ". Evidence bundle zipped to " + $z + " (contains a screenshot and page HTML; send it to the reviewer only).")
      exit 0
    }
    Write-Host ("Unexpected failure at stage " + $st + ". Bundle left in " + $b.FullName)
  }
}
if ($runCode -ne 0) { Write-Host "Run failed. Look in outputs\ for the evidence bundle."; exit 1 }
Write-Host "Done. See outputs\ (manifest.json, captured files)."
