# ============================================================================
# health-check.ps1
# 检查 junction 是否存在且指向正确目录。
# 失效时明确报错并退出码 1，禁止静默降级 legacy。
# 用法:
#   powershell -ExecutionPolicy Bypass -File health-check.ps1
#   powershell -ExecutionPolicy Bypass -File health-check.ps1 -JunctionPath "C:\ai-agent-collaboration" -ExpectedTarget "..."
# 退出码: 0 = 正常, 1 = junction 失效 (dual_agent 将无法加载)
# ============================================================================
param(
  [string]$JunctionPath = "C:\ai-agent-collaboration",
  [string]$ExpectedTarget = "C:\Users\<WINDOWS_USER>\ZCodeProject\无任何东西的文件夹\ai-agent-collaboration"
)

$ok = $true

# 1. junction 是否存在
if (-not (Test-Path $JunctionPath)) {
  Write-Output "[FAIL] junction 不存在: $JunctionPath"
  Write-Output "  影响: dual_agent 加载失败，会静默降级 legacy (并行被当讨论)。"
  Write-Output "  修复: 运行 create-junction.ps1 重建。"
  exit 1
}

$item = Get-Item $JunctionPath -Force

# 2. 是否为 junction 类型
if ($item.LinkType -ne 'Junction') {
  Write-Output "[FAIL] $JunctionPath 存在但非 junction (LinkType=$($item.LinkType))"
  Write-Output "  可能被误删后重建为普通目录，或被 git clone 覆盖。"
  $ok = $false
} else {
  # 3. 指向是否正确
  if ($item.Target -ne $ExpectedTarget) {
    Write-Output "[FAIL] junction 指向错误"
    Write-Output "  实际: $($item.Target)"
    Write-Output "  期望: $ExpectedTarget"
    $ok = $false
  } else {
    Write-Output "[OK] junction 有效: $JunctionPath -> $($item.Target)"
  }
}

# 4. dual_agent 目录是否可达 (junction 失效的关键症状)
$dualAgentDir = Join-Path $JunctionPath "dual_agent"
if (-not (Test-Path $dualAgentDir)) {
  Write-Output "[FAIL] dual_agent 目录不可达: $dualAgentDir"
  Write-Output "  这是 junction 失效或项目目录被移动的明确信号。"
  $ok = $false
} else {
  $initFile = Join-Path $dualAgentDir "__init__.py"
  if (-not (Test-Path $initFile)) {
    Write-Output "[WARN] dual_agent 目录存在但缺 __init__.py: $initFile"
    $ok = $false
  } else {
    Write-Output "[OK] dual_agent 可达: $dualAgentDir"
  }
}

# 5. 环境变量 AI_AGENT_COLLAB_ROOT 是否设置 (由 Hermes_Gateway.vbs 设)
$envRoot = $env:AI_AGENT_COLLAB_ROOT
if (-not $envRoot) {
  Write-Output "[WARN] 环境变量 AI_AGENT_COLLAB_ROOT 未设置"
  Write-Output "  若由 watchdog (非 vbs) 拉起 gateway，dual_agent 会加载失败 (P0-2)。"
  Write-Output "  Hermes_Gateway.vbs 会设置它，但 Hermes_Gateway_Watchdog.vbs 不会。"
} elseif ($envRoot -ne $JunctionPath) {
  Write-Output "[WARN] AI_AGENT_COLLAB_ROOT ($envRoot) 与 junction 路径 ($JunctionPath) 不一致"
  $ok = $false
} else {
  Write-Output "[OK] AI_AGENT_COLLAB_ROOT = $envRoot"
}

if (-not $ok) {
  Write-Output ""
  Write-Output "结论: junction 检查失败，dual_agent 可能降级 legacy。请勿继续，先修复。"
  exit 1
} else {
  Write-Output ""
  Write-Output "结论: junction 检查通过。"
  exit 0
}
