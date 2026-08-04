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

function Invoke-Git {
  param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
  & git @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw "git command failed with exit code $LASTEXITCODE"
  }
}

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
  return $normalizedPath
}

if (-not (Test-Path -LiteralPath (Join-Path $sourcePath ".git"))) {
  throw "SourceDir is not a git repository"
}

$head = (& git -C $sourcePath rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $head -ne $lock.source_commit) {
  throw "source commit mismatch: expected $($lock.source_commit), actual $head"
}

$dirty = @(& git -C $sourcePath status --porcelain)
if ($LASTEXITCODE -ne 0) { throw "unable to inspect source working tree" }
if ($dirty.Count -ne 0) {
  throw "source working tree must be clean before applying the locked patchset"
}

$autoCrlf = (& git -C $sourcePath config --get core.autocrlf).Trim()
if ($autoCrlf -notin @("false", "input")) {
  throw "source checkout must use LF files; clone with: git clone -c core.autocrlf=false"
}

try {
  foreach ($patch in $lock.patch_files) {
    $originalPatch = Join-Path $patchPath $patch.filename
    if (-not (Test-Path -LiteralPath $originalPatch -PathType Leaf)) {
      throw "locked patch is missing: $($patch.filename)"
    }
    $patchFile = Get-NormalizedPatch $originalPatch $patch.filename $patch.sha256
    Invoke-Git -C $sourcePath apply --check -- $patchFile
    Invoke-Git -C $sourcePath apply -- $patchFile
    Write-Output "applied $($patch.filename)"
  }
}
finally {
  $resolvedPatchDir = [System.IO.Path]::GetFullPath($normalizedPatchDir)
  $resolvedTemp = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
  if ($resolvedPatchDir.StartsWith($resolvedTemp, [System.StringComparison]::OrdinalIgnoreCase)) {
    Remove-Item -LiteralPath $resolvedPatchDir -Recurse -Force
  }
  $sha256.Dispose()
}

$status = @(& git -C $sourcePath status --short)
if ($LASTEXITCODE -ne 0 -or $status.Count -eq 0) {
  throw "patchset produced no source changes"
}

Write-Output "locked patchset $($lock.patchset_version) applied to $head"
