@echo off
rem Hermes Agent Gateway - Messaging Platform Integration
cd /d C:\Users\<WINDOWS_USER>\AppData\Local\hermes
set "HERMES_HOME=C:\Users\<WINDOWS_USER>\AppData\Local\hermes"
set "PYTHONIOENCODING=utf-8"
set "HERMES_GATEWAY_DETACHED=1"
set "VIRTUAL_ENV=C:\Users\<WINDOWS_USER>\AppData\Local\hermes\hermes-agent\venv"
rem 双 Agent 闭环核心模块根目录（迁移时改这一处即可；用 ASCII junction 路径避免 vbs 中文乱码）
set "AI_AGENT_COLLAB_ROOT=C:\ai-agent-collaboration"
set "PYTHONPATH=C:\Users\<WINDOWS_USER>\AppData\Local\hermes\hermes-agent;C:\Users\<WINDOWS_USER>\AppData\Local\hermes\hermes-agent\venv\Lib\site-packages;%PYTHONPATH%"
C:\Users\<WINDOWS_USER>\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\pythonw.exe -m hermes_cli.main gateway run
exit /b 0
