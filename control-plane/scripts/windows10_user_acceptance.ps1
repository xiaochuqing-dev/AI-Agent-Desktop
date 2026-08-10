param(
  [string]$ProductBundle = "",
  [string]$OutputPath = ".\windows10-user-acceptance-redacted.json"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-CandidateProbe {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Executable,
    [Parameter(Mandatory = $true)]
    [string]$Argument
  )

  $startInfo = New-Object System.Diagnostics.ProcessStartInfo
  $startInfo.FileName = $Executable
  $startInfo.Arguments = $Argument
  $startInfo.WorkingDirectory = Split-Path -Parent $Executable
  $startInfo.UseShellExecute = $false
  $startInfo.CreateNoWindow = $true
  $startInfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
  foreach ($name in @($startInfo.EnvironmentVariables.Keys)) {
    $key = [string]$name
    if ($key -match "^TELEGRAM_" -or $key -in @("CONTROL_PLANE_API_TOKEN", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")) {
      $startInfo.EnvironmentVariables.Remove($key)
    }
  }
  $startInfo.EnvironmentVariables["CONTROL_PLANE_DISABLE_LIVE_TELEGRAM"] = "1"
  $startInfo.EnvironmentVariables["QT_QPA_PLATFORM"] = "offscreen"

  $process = New-Object System.Diagnostics.Process
  $process.StartInfo = $startInfo
  try {
    if (-not $process.Start()) { throw "candidate probe could not start" }
    if (-not $process.WaitForExit(45000)) {
      try { $process.Kill() } catch { }
      throw "candidate probe timed out"
    }
    return [ordered]@{
      argument = $Argument
      exit_code = [int]$process.ExitCode
      passed = ($process.ExitCode -eq 0)
    }
  }
  finally {
    $process.Dispose()
  }
}

$started = [DateTime]::UtcNow
$os = Get-CimInstance -ClassName Win32_OperatingSystem
$isWindows10 = ([string]$os.Caption) -match "Windows 10"
$processArchitecture = [string]$env:PROCESSOR_ARCHITECTURE
$nativeArchitecture = [string]$env:PROCESSOR_ARCHITEW6432
$reportedArchitecture = [string]$os.OSArchitecture
$isX64 = [Environment]::Is64BitOperatingSystem -and (
  $processArchitecture -eq "AMD64" -or
  $nativeArchitecture -eq "AMD64" -or
  $reportedArchitecture -match "64"
)
$bundlePath = if ([string]::IsNullOrWhiteSpace($ProductBundle)) {
  [IO.Path]::GetFullPath($PSScriptRoot)
}
else {
  [IO.Path]::GetFullPath($ProductBundle)
}
$candidateExecutable = Join-Path $bundlePath "AI-Agent-Desktop.exe"
$manifestPath = Join-Path $bundlePath "candidate-manifest.json"
$candidateFound = Test-Path -LiteralPath $candidateExecutable -PathType Leaf
$manifestStatus = "missing"
$candidateVersion = $null
$candidateSha256 = $null
$versionProbe = $null
$headlessProbe = $null

if (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
  try {
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $candidateVersion = [string]$manifest.candidate_version
    $entries = @($manifest.files | Where-Object { ([string]$_.path).Replace('\', '/') -eq "AI-Agent-Desktop.exe" })
    if (
      $manifest.product -eq "AI-Agent-Desktop" -and
      $manifest.candidate_version -eq "0.2.0-gui" -and
      $manifest.platform -eq "windows" -and
      $manifest.architecture -eq "x64" -and
      [bool]$manifest.python_embedded -and
      -not [bool]$manifest.go_embedded -and
      -not [bool]$manifest.node_embedded -and
      -not [bool]$manifest.black_window -and
      $entries.Count -eq 1 -and
      $candidateFound
    ) {
      $candidateSha256 = (Get-FileHash -LiteralPath $candidateExecutable -Algorithm SHA256).Hash.ToLowerInvariant()
      $candidateSize = (Get-Item -LiteralPath $candidateExecutable).Length
      if ($candidateSha256 -eq ([string]$entries[0].sha256).ToLowerInvariant() -and $candidateSize -eq [long]$entries[0].size) {
        $manifestStatus = "valid"
      }
      else {
        $manifestStatus = "executable_mismatch"
      }
    }
    else {
      $manifestStatus = "invalid"
    }
  }
  catch {
    $manifestStatus = "unreadable"
  }
}

if ($candidateFound -and $manifestStatus -eq "valid") {
  try {
    $versionProbe = Invoke-CandidateProbe -Executable $candidateExecutable -Argument "--version"
  }
  catch {
    $versionProbe = [ordered]@{ argument = "--version"; exit_code = $null; passed = $false }
  }
  try {
    $headlessProbe = Invoke-CandidateProbe -Executable $candidateExecutable -Argument "--headless"
  }
  catch {
    $headlessProbe = [ordered]@{ argument = "--headless"; exit_code = $null; passed = $false }
  }
}

$candidateSmokePassed = (
  $manifestStatus -eq "valid" -and
  $null -ne $versionProbe -and [bool]$versionProbe.passed -and
  $null -ne $headlessProbe -and [bool]$headlessProbe.passed
)
$status = if (-not $isWindows10 -or -not $isX64) {
  "NOT_WINDOWS_10_X64"
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
  os_architecture = if ($reportedArchitecture) {
    $reportedArchitecture
  }
  elseif ($nativeArchitecture) {
    $nativeArchitecture
  }
  else {
    $processArchitecture
  }
  x64 = $isX64
  ordinary_user = -not [bool]([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
  product_bundle_supplied = -not [string]::IsNullOrWhiteSpace($ProductBundle)
  expected_candidate_version = "0.2.0-gui"
  observed_candidate_version = $candidateVersion
  candidate_executable_found = $candidateFound
  candidate_manifest_status = $manifestStatus
  candidate_executable_sha256 = $candidateSha256
  version_probe = $versionProbe
  headless_probe = $headlessProbe
  candidate_smoke_passed = $candidateSmokePassed
  four_step_gui_validation_required = $true
  four_step_gui_validated = $false
  requires_python = $false
  requires_go = $false
  requires_node = $false
  changes_system_configuration = $false
  report_contains_secret_values = $false
  real_telegram_access = $false
  telegram_messages_sent = 0
  note = "This offline wrapper never marks the four-step GUI or Telegram flow validated; user completion is still required on Windows 10 x64."
}

$target = [IO.Path]::GetFullPath($OutputPath)
$parent = Split-Path -Parent $target
if ($parent) { [IO.Directory]::CreateDirectory($parent) | Out-Null }
$utf8NoBom = New-Object Text.UTF8Encoding($false)
[IO.File]::WriteAllText($target, (($report | ConvertTo-Json -Depth 12) + [Environment]::NewLine), $utf8NoBom)
Write-Output $target
