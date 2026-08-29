param(
  [Parameter(Mandatory = $true)]
  [string]$SourceDir,
  [Parameter(Mandatory = $true)]
  [string]$OutputDir,
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

$sourcePath = (Resolve-Path -LiteralPath $SourceDir).Path
$lockPath = (Resolve-Path -LiteralPath $LockFile).Path
$lock = Get-Content -LiteralPath $lockPath -Raw -Encoding UTF8 | ConvertFrom-Json

if (-not (Test-Path -LiteralPath (Join-Path $sourcePath ".git"))) {
  throw "SourceDir is not a git repository"
}

$head = (& git -C $sourcePath rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $head -ne $lock.source_commit) {
  throw "source commit mismatch: expected $($lock.source_commit), actual $head"
}

$goVersionOutput = (& go version).Trim()
if ($LASTEXITCODE -ne 0) { throw "Go is required only on the build side" }
$expectedGoToken = "go$($lock.toolchain.go_version)"
if ($goVersionOutput -notmatch ("\b" + [regex]::Escape($expectedGoToken) + "\b")) {
  throw "Go version mismatch: expected $expectedGoToken, actual $goVersionOutput"
}

$patchMarker = Join-Path $sourcePath "platform\telegram\multiagent_metadata_test.go"
if (-not (Test-Path -LiteralPath $patchMarker -PathType Leaf)) {
  throw "locked patchset has not been applied"
}

$actualPatchedPaths = @(& git -C $sourcePath status --porcelain=v1 | ForEach-Object { $_.Substring(3).Replace("\", "/") } | Sort-Object)
if ($LASTEXITCODE -ne 0) { throw "unable to inspect patched source" }
$expectedPatchedPaths = @($lock.patched_files | ForEach-Object { $_.path } | Sort-Object)
if (($actualPatchedPaths -join "`n") -ne ($expectedPatchedPaths -join "`n")) {
  throw "patched source file set does not match the lock"
}
foreach ($file in $lock.patched_files) {
  $filePath = Join-Path $sourcePath $file.path
  $actualFileHash = (Get-FileHash -LiteralPath $filePath -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($actualFileHash -ne $file.sha256) {
    throw "patched source digest mismatch: $($file.path)"
  }
}

$outputPath = [System.IO.Path]::GetFullPath($OutputDir)
[System.IO.Directory]::CreateDirectory($outputPath) | Out-Null
$artifactPath = Join-Path $outputPath $lock.artifact_filename

$buildTags = @($lock.build.build_tags) -join " "
$shortCommit = $lock.source_commit.Substring(0, 7)
$buildTimestamp = ConvertTo-LockedString $lock.build.build_timestamp
$ldflags = ([string]$lock.build.ldflags_template).Replace('{version}', [string]$lock.version).Replace('{short_commit}', $shortCommit).Replace('{build_timestamp}', $buildTimestamp)

$previousEnvironment = @{}
foreach ($name in @("GOOS", "GOARCH", "CGO_ENABLED", "SOURCE_DATE_EPOCH", "GOTOOLCHAIN")) {
  $previousEnvironment[$name] = [System.Environment]::GetEnvironmentVariable($name, "Process")
}
try {
  $env:GOOS = $lock.toolchain.goos
  $env:GOARCH = $lock.toolchain.goarch
  $env:CGO_ENABLED = $lock.toolchain.cgo_enabled
  $env:SOURCE_DATE_EPOCH = [string]$lock.build.source_date_epoch
  $env:GOTOOLCHAIN = "local"
  Push-Location $sourcePath
  try {
    & go build -mod=readonly -trimpath -buildvcs=false -tags $buildTags -ldflags $ldflags -o $artifactPath ./cmd/cc-connect
    if ($LASTEXITCODE -ne 0) { throw "go build failed with exit code $LASTEXITCODE" }
  }
  finally {
    Pop-Location
  }
}
finally {
  foreach ($name in $previousEnvironment.Keys) {
    [System.Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], "Process")
  }
}

$artifactHash = (Get-FileHash -LiteralPath $artifactPath -Algorithm SHA256).Hash.ToLowerInvariant()
$artifactSize = (Get-Item -LiteralPath $artifactPath).Length
if ($null -eq $lock.PSObject.Properties["artifact_sha256"] -or $null -eq $lock.PSObject.Properties["artifact_size"]) {
  throw "locked artifact digest and size are required"
}
if ($artifactHash -ne [string]$lock.artifact_sha256 -or $artifactSize -ne [long]$lock.artifact_size) {
  throw "built artifact does not match the locked digest and size"
}
$patchFiles = @()
foreach ($patch in $lock.patch_files) {
  $patchFiles += [ordered]@{
    filename = $patch.filename
    sha256 = $patch.sha256
  }
}

$manifest = [ordered]@{
  schema_version = "1.0"
  component_id = $lock.component_id
  artifact_id = $lock.artifact_id
  platform = $lock.toolchain.goos
  architecture = $lock.toolchain.goarch
  source_repo = $lock.source_repo
  source_commit = $lock.source_commit
  upstream_version = $lock.upstream_version
  version = $lock.version
  patchset_version = $lock.patchset_version
  patch_files = $patchFiles
  patch_sha256 = @($lock.patch_files | ForEach-Object { $_.sha256 })
  go_version = $lock.toolchain.go_version
  build_tags = @($lock.build.build_tags)
  ldflags = $ldflags
  source_date_epoch = [long]$lock.build.source_date_epoch
  build_timestamp_policy = "locked_upstream_commit_timestamp_utc"
  artifact_filename = $lock.artifact_filename
  artifact_size = [long]$artifactSize
  artifact_sha256 = $artifactHash
  signature_status = $lock.signature_status
  created_at = $buildTimestamp
  compatibility = $lock.compatibility
  minimum_os = $lock.minimum_os
  install_layout_version = $lock.install_layout_version
  health_probe_version = $lock.health_probe_version
  health_probe = [ordered]@{
    mode = "version_only"
    deep_health = "unsupported"
    network_access = "none"
  }
}

$manifestPath = Join-Path $outputPath "cc-connect-artifact-manifest.json"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$manifestJson = $manifest | ConvertTo-Json -Depth 12
[System.IO.File]::WriteAllText($manifestPath, $manifestJson + [Environment]::NewLine, $utf8NoBom)
[System.IO.File]::WriteAllText((Join-Path $outputPath "cc-connect.sha256"), "$artifactHash  $($lock.artifact_filename)`n", $utf8NoBom)

Write-Output "artifact=$artifactPath"
Write-Output "manifest=$manifestPath"
Write-Output "sha256=$artifactHash"
Write-Output "size=$artifactSize"
