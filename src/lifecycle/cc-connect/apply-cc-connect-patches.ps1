# ============================================================================
# apply-cc-connect-patches.ps1
# 按顺序应用 cc-connect Patch 集到指定源码副本。
# 用法:
#   powershell -ExecutionPolicy Bypass -File apply-cc-connect-patches.ps1 `
#     -SourceDir "C:\path\to\cc-connect-src"
# 前提: SourceDir 是 cc-connect 在 fc315d2 的干净 clone。
# 安全: 失败时立即停止，已应用的 patch 保留在工作树（不自动回滚，便于诊断）。
# 退出码: 0 全部成功, 1 失败。
# ============================================================================
param(
  [Parameter(Mandatory = $true)]
  [string]$SourceDir,
  [string]$PatchDir = (Join-Path $PSScriptRoot "..\..\..\patches\cc-connect")
)

$ErrorActionPreference = "Stop"
$patches = @(
  "001-telegram-directed-routing",
  "002-hook-config-headers",
  "003-relay-response-prefix",
  "004-message-delivery-hooks",
  "005-windows-build-compat"
)

Write-Host "=== 应用 cc-connect Patch 集 ===" -ForegroundColor Cyan
Write-Host "源码: $SourceDir"
Write-Host "Patch: $PatchDir"
Write-Host ""

if (-not (Test-Path (Join-Path $SourceDir ".git"))) {
  Write-Error "$SourceDir 不是 git 仓库"
  exit 1
}

Push-Location $SourceDir
try {
  # 1. 行尾归一化为 LF（上游 blob 是 LF；autocrlf=true 的 clone 会是 CRLF，导致 patch 不匹配）
  git config core.autocrlf false | Out-Null
  Write-Host "归一化工作树为 LF..." -ForegroundColor DarkGray
  git checkout -- . 2>&1 | Out-Null
  git ls-files -z | ForEach-Object { $_ } | Out-Null
  git checkout HEAD -- . 2>&1 | Out-Null

  # 2. 校验起点干净
  $dirty = git status --porcelain 2>&1
  if ($dirty) {
    Write-Error "源码工作树非干净，拒绝应用。请先 git stash 或重新 clone。"
    exit 1
  }
  $head = git rev-parse HEAD 2>&1
  Write-Host "起点 HEAD: $head"

  # 3. 按顺序应用
  foreach ($p in $patches) {
    $patchFile = Join-Path $PatchDir "$p.patch"
    if (-not (Test-Path $patchFile)) {
      Write-Host "  [FAIL] $p : 文件不存在" -ForegroundColor Red
      exit 1
    }
    # 先 check 再 apply
    git apply --check $patchFile 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
      Write-Host "  [FAIL] $p : check 失败（可能前置 patch 未应用或源码版本不符）" -ForegroundColor Red
      exit 1
    }
    git apply $patchFile 2>&1
    if ($LASTEXITCODE -ne 0) {
      Write-Host "  [FAIL] $p : apply 失败" -ForegroundColor Red
      exit 1
    }
    Write-Host "  [ OK ] $p 已应用" -ForegroundColor Green
  }

  # 4. 汇总
  $modified = (git status --porcelain 2>&1 | Where-Object { $_ -match '^ M' }).Count
  $untracked = (git status --porcelain 2>&1 | Where-Object { $_ -match '^\?\?' }).Count
  Write-Host ""
  Write-Host "==> 全部 Patch 应用完成" -ForegroundColor Green
  Write-Host "    modified: $modified  untracked(新文件): $untracked"
  Write-Host "    预期: modified=10, untracked=2 (2 个新测试文件)"
  exit 0
} finally {
  Pop-Location
}
