param(
    [Parameter(Mandatory = $true)]
    [string]$SourceDir
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$SourceDir = [IO.Path]::GetFullPath($SourceDir)
$RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\..\.."))
$Lock = Get-Content -LiteralPath (Join-Path $RepoRoot "integrations\cc-connect\manifests\artifact-lock.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$Head = (& git -C $SourceDir rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $Head -ne [string]$Lock.source_commit) {
    throw "native config verification requires the exact locked source commit"
}

$SourceTest = Join-Path $RepoRoot "integrations\cc-connect\tests\native_config_compat_test.go"
$TargetTest = Join-Path $SourceDir "config\aiad_native_config_compat_test.go"
$LegacyFixture = Join-Path $RepoRoot "integrations\cc-connect\fixtures\native-v1-legacy.toml"
$CurrentFixture = Join-Path $RepoRoot "integrations\cc-connect\fixtures\native-v2-current.toml"
if (Test-Path -LiteralPath $TargetTest) {
    throw "refusing to overwrite an existing source test: $TargetTest"
}
if ((Get-FileHash -LiteralPath $LegacyFixture -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $CurrentFixture -Algorithm SHA256).Hash) {
    throw "legacy and current native TOML fixtures are not byte-identical"
}

try {
    Copy-Item -LiteralPath $SourceTest -Destination $TargetTest
    $env:AIAD_NATIVE_CONFIG_FIXTURE_LEGACY = $LegacyFixture
    $env:AIAD_NATIVE_CONFIG_FIXTURE_CURRENT = $CurrentFixture
    $env:CGO_ENABLED = "0"
    Push-Location -LiteralPath $SourceDir
    try {
        & go test -mod=readonly -tags "no_web goolm no_pi" ./config -run "^TestAIADNativeConfigCompatibility$" -count=1
        if ($LASTEXITCODE -ne 0) {
            throw "v1.5.0 rejected an AI-Agent-Desktop native TOML fixture"
        }
    }
    finally {
        Pop-Location
    }
    [ordered]@{
        status = "passed"
        source_commit = [string]$Lock.source_commit
        legacy_fixture_sha256 = (Get-FileHash -LiteralPath $LegacyFixture -Algorithm SHA256).Hash.ToLowerInvariant()
        current_fixture_sha256 = (Get-FileHash -LiteralPath $CurrentFixture -Algorithm SHA256).Hash.ToLowerInvariant()
        semantic_change = "none"
        environment_placeholders = "resolved"
        project_types = @("claudecode", "codex")
    } | ConvertTo-Json -Depth 4 -Compress
}
finally {
    if (Test-Path -LiteralPath $TargetTest) {
        Remove-Item -LiteralPath $TargetTest -Force
    }
}
