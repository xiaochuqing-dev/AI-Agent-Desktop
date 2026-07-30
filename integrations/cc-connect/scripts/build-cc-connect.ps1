# ============================================================================
# build-cc-connect.ps1
# 从已应用 Patch 的 cc-connect 源码副本构建候选二进制。
# 读取 versions.lock 获取版本信息；输出到独立目录，绝不覆盖 npm 全局运行二进制。
# 用法:
#   powershell -ExecutionPolicy Bypass -File build-cc-connect.ps1 `
#     -SourceDir "C:\path\to\cc-connect-src-patched" `
#     [-OutputDir "C:\path\to\output"]
# 前提:
#   - SourceDir 已应用全部 Patch (apply-cc-connect-patches.ps1)
#   - 本机已安装 Go (见 versions.lock 的 go 版本)
# 退出码: 0 成功, 1 失败。
# ============================================================================
param(
  [Parameter(Mandatory = $true)]
  [string]$SourceDir,
  [string]$OutputDir = (Join-Path $PSScriptRoot "..\..\..\build\output"),
  [string]$VersionsLock = (Join-Path $PSScriptRoot "..\..\..\VERSIONS.lock")
)

$ErrorActionPreference = "Stop"

# 从 versions.lock 读取构建参数（自定义格式，用正则提取）
function Read-LockValue($path, $key) {
  if (-not (Test-Path $path)) { return $null }
  $content = Get-Content $path -Raw -Encoding UTF8
  # 匹配 key = "value" 或 key = value
  $m = [regex]::Match($content, "(?m)^\s*$key\s*=\s*`"?([^`"\r\n]+)`"?")
  if ($m.Success) { return $m.Groups[1].Value.Trim() }
  return $null
}

$sourceCommit   = Read-LockValue $VersionsLock "head_commit"
$npmVersion     = Read-LockValue $VersionsLock "package_version"
$goVersionLock  = Read-LockValue $VersionsLock "go"
# 短 sha
$shortSha = if ($sourceCommit) { $sourceCommit.Substring(0,7) } else { "unknown" }

# 版本号构成：upstream-version + patchset-version + source-short-sha（按用户决策）
$PatchsetVersion = "0.1"
$versionStr = if ($npmVersion) { "v$npmVersion-patchset$PatchsetVersion-$shortSha" } else { "v0.1-$shortSha" }
$buildTime = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")

# 构建参数（来自 patches/cc-connect/README.md，固化 ldflags）
$buildTags = "no_web goolm no_pi"
$ldflags = "-s -w -X main.version=$versionStr -X main.commit=$shortSha -X main.buildTime=$buildTime"

Write-Host "=== 构建 cc-connect 候选二进制 ===" -ForegroundColor Cyan
Write-Host "源码:          $SourceDir"
Write-Host "versions.lock: $VersionsLock"
Write-Host "source commit: $sourceCommit"
Write-Host "npm version:   $npmVersion"
Write-Host "go (lock):     $goVersionLock"
Write-Host "go (实际):     $(go version)"
Write-Host "build tags:    $buildTags"
Write-Host "version:       $versionStr"
Write-Host "buildTime:     $buildTime"
Write-Host "output dir:    $OutputDir"
Write-Host ""

if (-not (Test-Path (Join-Path $SourceDir ".git"))) {
  Write-Error "$SourceDir 不是 git 仓库"
  exit 1
}

# 校验源码已应用 patch（含 recordSent 说明 004 已应用）
Push-Location $SourceDir
try {
  $checkFile = "platform/telegram/telegram.go"
  if (-not (Test-Path $checkFile)) { Write-Error "非 cc-connect 源码目录"; exit 1 }
  $hasPatch = Select-String -Path $checkFile -Pattern "recordSent" -Quiet
  if (-not $hasPatch) {
    Write-Error "源码未应用 Patch（无 recordSent）。请先运行 apply-cc-connect-patches.ps1"
    exit 1
  }
  Write-Host "源码已应用 Patch（检测到 recordSent）" -ForegroundColor Green

  # 确保 LF
  git config core.autocrlf false | Out-Null

  # 输出目录
  if (-not (Test-Path $OutputDir)) { New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null }
  $candidate = Join-Path $OutputDir "cc-connect-candidate.exe"

  Write-Host ""
  Write-Host "开始 go build..." -ForegroundColor Cyan
  $env:GOFLAGS = "-mod=mod"
  go build -tags $buildTags -ldflags $ldflags -o $candidate ./cmd/cc-connect 2>&1
  if ($LASTEXITCODE -ne 0) {
    Write-Error "go build 失败 (exit $LASTEXITCODE)"
    exit 1
  }
  Write-Host "build 成功" -ForegroundColor Green

  # 验证版本
  Write-Host ""
  Write-Host "=== 候选二进制 --version ===" -ForegroundColor Cyan
  & $candidate --version

  # SHA256
  $hash = (Get-FileHash $candidate -Algorithm SHA256).Hash.ToLower()
  $size = (Get-Item $candidate).Length
  Write-Host ""
  Write-Host "=== SHA256 ===" -ForegroundColor Cyan
  Write-Host "  $hash"
  Write-Host "  大小: $size bytes ($([math]::Round($size/1MB,2)) MB)"
  Write-Host "  路径: $candidate"

  # 写构建记录
  $record = Join-Path $OutputDir "build-manifest.txt"
  $lines = @(
    "cc-connect candidate build manifest"
    "buildTime:     $buildTime"
    "sourceCommit:  $sourceCommit"
    "npmVersion:    $npmVersion"
    "patchset:      $PatchsetVersion"
    "version:       $versionStr"
    "buildTags:     $buildTags"
    "ldflags:       $ldflags"
    "goVersion:     $(go version)"
    "sha256:        $hash"
    "size:          $size"
    "candidate:     $candidate"
    "note:          候选产物，未覆盖 npm 全局运行二进制；等待单独验收后再替换。"
  )
  $lines | Set-Content -Path $record -Encoding UTF8
  Write-Host ""
  Write-Host "构建记录: $record" -ForegroundColor DarkGray
  Write-Host ""
  Write-Host "==> 构建完成。候选二进制未触碰运行系统。" -ForegroundColor Green
  exit 0
} finally {
  Pop-Location
}
