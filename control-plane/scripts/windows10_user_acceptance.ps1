param(
  [string]$ProductBundle,
  [string]$OutputPath = ".\windows10-user-acceptance-redacted.json"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$started = [DateTime]::UtcNow
$os = Get-CimInstance -ClassName Win32_OperatingSystem
$isWindows10 = ([string]$os.Caption) -match "Windows 10"
$isX64 = [Environment]::Is64BitOperatingSystem
$runnerFound = $false
$runnerStatus = "not_run"
$runnerReport = $null

if ($ProductBundle) {
  $bundlePath = [IO.Path]::GetFullPath($ProductBundle)
  $runner = Join-Path $bundlePath "ai-agent-desktop-windows10-acceptance.exe"
  if (Test-Path -LiteralPath $runner -PathType Leaf) {
    $runnerFound = $true
    $temporaryReport = Join-Path ([IO.Path]::GetTempPath()) ("ai-agent-desktop-win10-" + [guid]::NewGuid().ToString("N") + ".json")
    try {
      & $runner --output $temporaryReport
      if ($LASTEXITCODE -ne 0) { throw "packaged acceptance runner failed" }
      $runnerReport = Get-Content -LiteralPath $temporaryReport -Raw -Encoding UTF8 | ConvertFrom-Json
      $runnerStatus = "completed"
    }
    finally {
      Remove-Item -LiteralPath $temporaryReport -Force -ErrorAction SilentlyContinue
    }
  }
  else {
    $runnerStatus = "packaged_runner_missing"
  }
}

$status = if (-not $isWindows10 -or -not $isX64) {
  "NOT_WINDOWS_10_X64"
}
elseif ($runnerStatus -eq "completed") {
  [string]$runnerReport.status
}
else {
  "PENDING_USER_REAL_MACHINE_VALIDATION"
}

$report = [ordered]@{
  schema_version = "1.0"
  status = $status
  started_at = $started.ToString("o")
  completed_at = [DateTime]::UtcNow.ToString("o")
  os_caption = [string]$os.Caption
  os_build = [string]$os.BuildNumber
  x64 = $isX64
  ordinary_user = -not [bool]([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
  product_bundle_supplied = [bool]$ProductBundle
  packaged_runner_found = $runnerFound
  packaged_runner_status = $runnerStatus
  requires_python = $false
  requires_go = $false
  requires_node = $false
  report_contains_secret_values = $false
  telegram_messages_sent = 0
  note = "This wrapper never marks Windows 10 validated unless the packaged acceptance runner completes on a Windows 10 x64 machine."
  packaged_runner_result = $runnerReport
}

$target = [IO.Path]::GetFullPath($OutputPath)
$parent = Split-Path -Parent $target
if ($parent) { [IO.Directory]::CreateDirectory($parent) | Out-Null }
$utf8NoBom = New-Object Text.UTF8Encoding($false)
[IO.File]::WriteAllText($target, (($report | ConvertTo-Json -Depth 12) + [Environment]::NewLine), $utf8NoBom)
Write-Output $target
