param(
    [string]$ReportPath = "reports/selenium/report.html",
    [string]$Browser = "auto",
    [switch]$Headed,
    [switch]$OpenReport
)

$ErrorActionPreference = "Stop"

$venvPython = Join-Path $PSScriptRoot ".venv/Scripts/python.exe"
$pythonExe = if (Test-Path $venvPython) { $venvPython } else { "python" }

$env:SELENIUM_BROWSER = $Browser
$env:SELENIUM_HEADLESS = if ($Headed) { "0" } else { "1" }

$reportDir = Split-Path -Parent $ReportPath
if (-not [string]::IsNullOrWhiteSpace($reportDir)) {
    New-Item -ItemType Directory -Path $reportDir -Force | Out-Null
}

Write-Host "Running Selenium suite..."
Write-Host "Browser: $Browser | Headless: $(-not $Headed)"

$junitPath = Join-Path $reportDir "junit.xml"

& $pythonExe -m pytest tests/selenium -m selenium --junitxml="$junitPath"
$pytestExitCode = $LASTEXITCODE

& $pythonExe tests/selenium/build_html_report.py --input "$junitPath" --output "$ReportPath"
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to build HTML report from junit xml."
    exit 1
}

$resolvedReport = Resolve-Path $ReportPath
Write-Host "Report generated at: $resolvedReport"

if ($OpenReport) {
    Start-Process $resolvedReport
}

exit $pytestExitCode
