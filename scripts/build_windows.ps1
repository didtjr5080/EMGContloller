param([string]$Python = '.venv/Scripts/python.exe')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $projectRoot
try {
    & $Python -m PyInstaller --noconfirm --distpath dist --workpath build/pyinstaller EMGController.spec
    if ($LASTEXITCODE -ne 0) { throw 'Executable build failed.' }
    $executablePath = Join-Path $projectRoot 'dist/EMGController.exe'
    $reportPath = Join-Path $projectRoot 'build/windows-self-test.json'
    $checkProcess = Start-Process -FilePath $executablePath -ArgumentList @('--self-test', ('"' + $reportPath + '"')) -WindowStyle Hidden -PassThru -Wait
    if ($checkProcess.ExitCode -ne 0) { throw "Packaged self-test failed; see $reportPath" }
    $report = Get-Content -Raw -LiteralPath $reportPath | ConvertFrom-Json
    if (-not $report.ok) { throw "Packaged self-test failed; see $reportPath" }
    Write-Output $executablePath
} finally {
    Pop-Location
}
exit 0
