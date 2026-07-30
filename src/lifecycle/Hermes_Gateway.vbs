' Hermes Agent Gateway - Messaging Platform Integration
Option Explicit
Dim sh, env, existing_pp
Set sh = CreateObject("WScript.Shell")
Set env = sh.Environment("PROCESS")
env.Item("HERMES_HOME") = "C:\Users\<WINDOWS_USER>\AppData\Local\hermes"
env.Item("PYTHONIOENCODING") = "utf-8"
env.Item("HERMES_GATEWAY_DETACHED") = "1"
env.Item("VIRTUAL_ENV") = "C:\Users\<WINDOWS_USER>\AppData\Local\hermes\hermes-agent\venv"
' 双 Agent 闭环核心模块（dual_agent）根目录。multiagent 适配层据此加载
' 独立可复用的并行/顺序/聚合逻辑。改这个路径即可迁移，不用动脚本逻辑。
' 用 ASCII junction 路径（C:\ai-agent-collaboration -> 真实中文路径），
' 避免 vbs 中文路径被 GBK 解码成乱码导致 dual_agent 加载失败。
env.Item("AI_AGENT_COLLAB_ROOT") = "C:\ai-agent-collaboration"
existing_pp = env.Item("PYTHONPATH")
If Len(existing_pp) > 0 Then
  env.Item("PYTHONPATH") = "C:\Users\<WINDOWS_USER>\AppData\Local\hermes\hermes-agent;C:\Users\<WINDOWS_USER>\AppData\Local\hermes\hermes-agent\venv\Lib\site-packages;" & existing_pp
Else
  env.Item("PYTHONPATH") = "C:\Users\<WINDOWS_USER>\AppData\Local\hermes\hermes-agent;C:\Users\<WINDOWS_USER>\AppData\Local\hermes\hermes-agent\venv\Lib\site-packages"
End If
sh.CurrentDirectory = "C:\Users\<WINDOWS_USER>\AppData\Local\hermes"
sh.Run "C:\Users\<WINDOWS_USER>\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\pythonw.exe -m hermes_cli.main gateway run", 0, False
