param([string]$Inputs = "inputs\invoice.json", [string]$CodeSource = "relay", [string]$FailAt = "")
$ErrorActionPreference = "Stop"
$args2 = @("-m","portal_runner","run","--inputs",$Inputs,"--code-source",$CodeSource)
if ($FailAt) { $args2 += @("--fail-at",$FailAt) }
.\.venv\Scripts\python.exe @args2
