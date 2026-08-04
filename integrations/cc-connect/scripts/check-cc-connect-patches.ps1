param(
  [Parameter(Mandatory = $true)]
  [string]$SourceDir,
  [string]$PatchDir,
  [string]$LockFile
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if (-not $PatchDir) { $PatchDir = Join-Path $PSScriptRoot "..\patches" }
if (-not $LockFile) { $LockFile = Join-Path $PSScriptRoot "..\manifests\artifact-lock.json" }

$sourcePath = (Resolve-Path -LiteralPath $SourceDir).Path
$patchPath = (Resolve-Path -LiteralPath $PatchDir).Path
$lockPath = (Resolve-Path -LiteralPath $LockFile).Path
$lock = Get-Content -LiteralPath $lockPath -Raw -Encoding UTF8 | ConvertFrom-Json
$normalizedPatchDir = Join-Path ([System.IO.Path]::GetTempPath()) ("cc-connect-patches-" + [guid]::NewGuid().ToString("N"))
[System.IO.Directory]::CreateDirectory($normalizedPatchDir) | Out-Null
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$sha256 = [System.Security.Cryptography.SHA256]::Create()

function Get-NormalizedPatch {
  param([string]$OriginalPath, [string]$Filename, [string]$ExpectedHash)
  $content = [System.IO.File]::ReadAllText($OriginalPath, [System.Text.Encoding]::UTF8).Replace("`r`n", "`n")
  $bytes = $utf8NoBom.GetBytes($content)
  $actualHash = ([System.BitConverter]::ToString($sha256.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
  if ($actualHash -ne $ExpectedHash) { throw "patch digest mismatch for $Filename" }
  $normalizedPath = Join-Path $normalizedPatchDir $Filename
  [System.IO.File]::WriteAllBytes($normalizedPath, $bytes)
  return [pscustomobject]@{ Path = $normalizedPath; Hash = $actualHash }
}

if (-not (Test-Path -LiteralPath (Join-Path $sourcePath ".git"))) {
  throw "SourceDir is not a git repository"
}

$head = (& git -C $sourcePath rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $head -ne $lock.source_commit) {
  throw "source commit mismatch: expected $($lock.source_commit), actual $head"
}

$dirty = @(& git -C $sourcePath status --porcelain)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -ne 0) {
  throw "source working tree must be clean"
}

$probeDir = Join-Path ([System.IO.Path]::GetTempPath()) ("cc-connect-patch-check-" + [guid]::NewGuid().ToString("N"))
$probeCreated = $false
try {
  & git -C $sourcePath worktree add --detach $probeDir $lock.source_commit | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "unable to create detached patch-check worktree" }
  $probeCreated = $true
  & git -C $probeDir config core.autocrlf false
  if ($LASTEXITCODE -ne 0) { throw "unable to configure LF checkout" }

  foreach ($patch in $lock.patch_files) {
    $originalPatch = Join-Path $patchPath $patch.filename
    if (-not (Test-Path -LiteralPath $originalPatch -PathType Leaf)) {
      throw "locked patch is missing: $($patch.filename)"
    }
    $normalized = Get-NormalizedPatch $originalPatch $patch.filename $patch.sha256
    & git -C $probeDir apply --check -- $normalized.Path
    if ($LASTEXITCODE -ne 0) { throw "patch check failed: $($patch.filename)" }
    & git -C $probeDir apply -- $normalized.Path
    if ($LASTEXITCODE -ne 0) { throw "patch application failed: $($patch.filename)" }
    Write-Output "verified $($patch.filename) $($normalized.Hash)"
  }

  Write-Output "all locked patches apply sequentially to $head"
}
finally {
  if ($probeCreated) {
    & git -C $sourcePath worktree remove --force $probeDir | Out-Null
  }
  elseif (Test-Path -LiteralPath $probeDir) {
    $resolvedProbe = [System.IO.Path]::GetFullPath($probeDir)
    $resolvedTemp = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
    if ($resolvedProbe.StartsWith($resolvedTemp, [System.StringComparison]::OrdinalIgnoreCase)) {
      Remove-Item -LiteralPath $resolvedProbe -Recurse -Force
    }
  }
  $resolvedPatchDir = [System.IO.Path]::GetFullPath($normalizedPatchDir)
  $resolvedTemp = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
  if ($resolvedPatchDir.StartsWith($resolvedTemp, [System.StringComparison]::OrdinalIgnoreCase)) {
    Remove-Item -LiteralPath $resolvedPatchDir -Recurse -Force
  }
  $sha256.Dispose()
}
