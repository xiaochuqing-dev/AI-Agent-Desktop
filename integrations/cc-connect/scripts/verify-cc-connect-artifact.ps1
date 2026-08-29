param(
  [Parameter(Mandatory = $true)]
  [string]$BundleDir,
  [string]$LockFile
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if (-not $LockFile) { $LockFile = Join-Path $PSScriptRoot "..\manifests\artifact-lock.json" }

function ConvertTo-LockedString {
  param([object]$Value)
  if ($Value -is [datetime]) {
    return $Value.ToUniversalTime().ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", [System.Globalization.CultureInfo]::InvariantCulture)
  }
  return [string]$Value
}

$bundlePath = (Resolve-Path -LiteralPath $BundleDir).Path
$lockPath = (Resolve-Path -LiteralPath $LockFile).Path
$lock = Get-Content -LiteralPath $lockPath -Raw -Encoding UTF8 | ConvertFrom-Json
$manifestPath = Join-Path $bundlePath "cc-connect-artifact-manifest.json"
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
  throw "artifact manifest is missing"
}
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json

$required = @(
  "schema_version", "component_id", "artifact_id", "platform", "architecture",
  "source_repo", "source_commit", "upstream_version", "version", "patchset_version",
  "patch_files", "patch_sha256", "go_version", "build_tags", "ldflags",
  "source_date_epoch", "build_timestamp_policy", "artifact_filename", "artifact_size", "artifact_sha256",
  "signature_status", "created_at", "compatibility", "minimum_os",
  "install_layout_version", "health_probe_version", "health_probe"
)
foreach ($name in $required) {
  if ($null -eq $manifest.PSObject.Properties[$name]) { throw "manifest field is missing: $name" }
}

if ($manifest.component_id -ne $lock.component_id -or $manifest.artifact_id -ne $lock.artifact_id) {
  throw "artifact identity does not match the lock"
}
if ($manifest.source_commit -ne $lock.source_commit -or $manifest.patchset_version -ne $lock.patchset_version) {
  throw "source or patchset does not match the lock"
}
if ($manifest.schema_version -ne $lock.schema_version -or $manifest.source_repo -ne $lock.source_repo -or $manifest.upstream_version -ne $lock.upstream_version -or $manifest.version -ne $lock.version) {
  throw "artifact version provenance does not match the lock"
}
if ($manifest.platform -ne "windows" -or $manifest.architecture -ne "amd64") {
  throw "only windows/amd64 is supported"
}
if ($manifest.signature_status -ne "unsigned") {
  throw "unexpected signature status"
}
$expectedVersion = [string]$lock.version
$expectedCommit = [string]$lock.source_commit
$expectedBuildTimestamp = ConvertTo-LockedString $lock.build.build_timestamp
$expectedGoVersion = [string]$lock.toolchain.go_version
$expectedLdflags = ([string]$lock.build.ldflags_template).Replace('{version}', $expectedVersion).Replace('{short_commit}', $expectedCommit.Substring(0, 7)).Replace('{build_timestamp}', $expectedBuildTimestamp)
if ([string]$manifest.go_version -cne $expectedGoVersion) {
  throw "toolchain does not match the lock"
}
if ([string]$manifest.ldflags -cne $expectedLdflags) {
  throw "ldflags do not match the lock"
}
if ([long]$manifest.source_date_epoch -ne [long]$lock.build.source_date_epoch -or (ConvertTo-LockedString $manifest.created_at) -ne $expectedBuildTimestamp -or $manifest.build_timestamp_policy -ne "locked_upstream_commit_timestamp_utc") {
  throw "reproducible build timestamp inputs do not match the lock"
}
if ((@($manifest.build_tags) -join "`n") -ne (@($lock.build.build_tags) -join "`n")) {
  throw "build tags do not match the lock"
}
if (@($manifest.patch_files).Count -ne @($lock.patch_files).Count -or @($manifest.patch_sha256).Count -ne @($lock.patch_files).Count) {
  throw "patch projection count does not match the lock"
}
for ($index = 0; $index -lt @($lock.patch_files).Count; $index++) {
  if ($manifest.patch_files[$index].filename -ne $lock.patch_files[$index].filename -or $manifest.patch_files[$index].sha256 -ne $lock.patch_files[$index].sha256 -or $manifest.patch_sha256[$index] -ne $lock.patch_files[$index].sha256) {
    throw "patch projection does not match the lock at index $index"
  }
}
if ($manifest.minimum_os -ne $lock.minimum_os -or $manifest.install_layout_version -ne $lock.install_layout_version -or $manifest.health_probe_version -ne $lock.health_probe_version) {
  throw "compatibility metadata does not match the lock"
}
if ($manifest.health_probe.mode -ne "version_only" -or $manifest.health_probe.deep_health -ne "unsupported" -or $manifest.health_probe.network_access -ne "none") {
  throw "health probe metadata is invalid"
}
if ([System.IO.Path]::GetFileName($manifest.artifact_filename) -ne $manifest.artifact_filename -or $manifest.artifact_filename -ne "cc-connect.exe") {
  throw "unsafe artifact filename"
}

$artifactPath = Join-Path $bundlePath $manifest.artifact_filename
if (-not (Test-Path -LiteralPath $artifactPath -PathType Leaf)) { throw "artifact is missing" }
$actualSize = (Get-Item -LiteralPath $artifactPath).Length
if ($actualSize -ne [long]$manifest.artifact_size) { throw "artifact size mismatch" }
$actualHash = (Get-FileHash -LiteralPath $artifactPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualHash -ne $manifest.artifact_sha256) { throw "artifact SHA256 mismatch" }
if ($actualSize -ne [long]$lock.artifact_size -or $actualHash -ne [string]$lock.artifact_sha256) {
  throw "artifact does not match the locked digest and size"
}
$shaPath = Join-Path $bundlePath "cc-connect.sha256"
if (-not (Test-Path -LiteralPath $shaPath -PathType Leaf)) { throw "artifact SHA256 sidecar is missing" }
$shaText = (Get-Content -LiteralPath $shaPath -Raw -Encoding UTF8).Trim()
if ($shaText -ne "$actualHash  $($manifest.artifact_filename)") { throw "artifact SHA256 sidecar mismatch" }

$bytes = [System.IO.File]::ReadAllBytes($artifactPath)
if ($bytes.Length -lt 512 -or $bytes[0] -ne 0x4d -or $bytes[1] -ne 0x5a) {
  throw "artifact is not a PE executable"
}
$peOffset = [System.BitConverter]::ToInt32($bytes, 0x3c)
if ($peOffset -lt 0 -or ($peOffset + 6) -gt $bytes.Length) { throw "invalid PE header offset" }
if ($bytes[$peOffset] -ne 0x50 -or $bytes[$peOffset + 1] -ne 0x45 -or $bytes[$peOffset + 2] -ne 0 -or $bytes[$peOffset + 3] -ne 0) {
  throw "invalid PE signature"
}
$machine = [System.BitConverter]::ToUInt16($bytes, $peOffset + 4)
if ($machine -ne 0x8664) { throw "artifact PE architecture is not AMD64" }

$probeRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("cc-connect-version-probe-" + [guid]::NewGuid().ToString("N"))
$listener = $null
$process = $null
try {
  [System.IO.Directory]::CreateDirectory($probeRoot) | Out-Null
  [System.IO.Directory]::CreateDirectory((Join-Path $probeRoot ".cc-connect")) | Out-Null
  [System.IO.Directory]::CreateDirectory((Join-Path $probeRoot "Temp")) | Out-Null
  $endpoint = New-Object System.Net.IPEndPoint ([System.Net.IPAddress]::Loopback, 0)
  $listener = New-Object System.Net.Sockets.TcpListener $endpoint
  $listener.Start()
  $healthPort = ([System.Net.IPEndPoint]$listener.LocalEndpoint).Port
  $listener.Stop()
  $listener = $null
  [System.IO.File]::WriteAllText((Join-Path $probeRoot ".cc-connect\config.toml"), "# Synthetic offline health probe`nbind = `"127.0.0.1:$healthPort`"`n", (New-Object System.Text.UTF8Encoding($false)))

  $startInfo = New-Object System.Diagnostics.ProcessStartInfo
  $startInfo.FileName = $artifactPath
  $startInfo.Arguments = "--version"
  $startInfo.WorkingDirectory = $probeRoot
  $startInfo.UseShellExecute = $false
  $startInfo.CreateNoWindow = $true
  $startInfo.RedirectStandardOutput = $true
  $startInfo.RedirectStandardError = $true
  $startInfo.EnvironmentVariables.Clear()
  $systemRoot = if ($env:SystemRoot) { $env:SystemRoot } else { "C:\Windows" }
  $safeEnvironment = [ordered]@{
    SystemRoot = $systemRoot
    WINDIR = $systemRoot
    PATH = (Join-Path $systemRoot "System32")
    PATHEXT = ".COM;.EXE;.BAT;.CMD"
    HOME = $probeRoot
    USERPROFILE = $probeRoot
    LOCALAPPDATA = (Join-Path $probeRoot "LocalAppData")
    APPDATA = (Join-Path $probeRoot "AppData")
    TEMP = (Join-Path $probeRoot "Temp")
    TMP = (Join-Path $probeRoot "Temp")
    NO_PROXY = "*"
    HTTP_PROXY = ""
    HTTPS_PROXY = ""
    ALL_PROXY = ""
    CC_CONNECT_HEALTH_PORT = [string]$healthPort
    CC_CONNECT_HEALTH_MODE = "version-only-offline"
  }
  foreach ($entry in $safeEnvironment.GetEnumerator()) {
    $startInfo.EnvironmentVariables[$entry.Key] = $entry.Value
  }
  $process = New-Object System.Diagnostics.Process
  $process.StartInfo = $startInfo
  if (-not $process.Start()) { throw "unable to start isolated artifact version probe" }
  $stdoutTask = $process.StandardOutput.ReadToEndAsync()
  $stderrTask = $process.StandardError.ReadToEndAsync()
  if (-not $process.WaitForExit(10000)) {
    & (Join-Path $systemRoot "System32\taskkill.exe") /PID $process.Id /T /F | Out-Null
    throw "artifact --version timed out"
  }
  $process.WaitForExit()
  $versionText = ($stdoutTask.Result + "`n" + $stderrTask.Result).Trim()
  if ($process.ExitCode -ne 0) { throw "artifact --version failed" }
  $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $($process.Id)" -ErrorAction SilentlyContinue)
  if ($children.Count -ne 0) {
    foreach ($child in $children) { & (Join-Path $systemRoot "System32\taskkill.exe") /PID $child.ProcessId /T /F | Out-Null }
    throw "artifact version probe left child processes"
  }
  if ($versionText -notmatch [regex]::Escape($lock.version)) { throw "artifact version does not match the lock" }
  if ($versionText -notmatch [regex]::Escape($lock.source_commit.Substring(0, 7))) { throw "artifact commit does not match the lock" }
}
finally {
  if ($listener) { $listener.Stop() }
  if ($process) {
    if (-not $process.HasExited) { & "$env:SystemRoot\System32\taskkill.exe" /PID $process.Id /T /F | Out-Null }
    $process.Dispose()
  }
  $resolvedProbe = [System.IO.Path]::GetFullPath($probeRoot)
  $resolvedTemp = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
  if ((Test-Path -LiteralPath $resolvedProbe) -and $resolvedProbe.StartsWith($resolvedTemp, [System.StringComparison]::OrdinalIgnoreCase)) {
    Remove-Item -LiteralPath $resolvedProbe -Recurse -Force
  }
}

Write-Output "verified_artifact=$artifactPath"
Write-Output "sha256=$actualHash"
Write-Output "pe_machine=0x8664"
Write-Output "signature_status=$($manifest.signature_status)"
