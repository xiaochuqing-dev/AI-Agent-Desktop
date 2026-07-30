@echo off
rem =============================================================================
rem cc-connect Autostart Launcher (Stage 1.5)
rem Reads bot tokens from .env and starts cc-connect with the group config.
rem This .cmd is invoked by CcConnect_Autostart.vbs at Windows startup.
rem =============================================================================
setlocal enabledelayedexpansion

set "ENV_FILE=C:\Users\<WINDOWS_USER>\.cc-connect\bot-tokens.env"
set "CONFIG=C:\Users\<WINDOWS_USER>\.cc-connect\config.toml"
set "CC_HOME=C:\Users\<WINDOWS_USER>\.cc-connect"

rem --- Load .env (KEY=VALUE lines, skip comments) ---
if not exist "%ENV_FILE%" (
    echo [cc-connect-autostart] .env not found: %ENV_FILE% >> "%CC_HOME%\logs\autostart.log" 2>&1
    exit /b 1
)

for /f "usebackq eol=# tokens=1,* delims==" %%K in ("%ENV_FILE%") do (
    set "%%K=%%V"
)

rem --- Unset CLAUDECODE so claude CLI can be spawned ---
set "CLAUDECODE="

rem --- Start cc-connect (force kills any existing instance) ---
cd /d "%CC_HOME%"
"%LOCALAPPDATA%\..\Roaming\npm\cc-connect.cmd" --config "%CONFIG%" --force >> "%CC_HOME%\logs\autostart.log" 2>&1
