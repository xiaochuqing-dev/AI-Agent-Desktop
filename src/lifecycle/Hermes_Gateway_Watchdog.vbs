Option Explicit

Dim shell, environment, commandLine, exitCode

Set shell = CreateObject("WScript.Shell")
Set environment = shell.Environment("PROCESS")
environment.Item("HERMES_HOME") = "C:\Users\<WINDOWS_USER>\AppData\Local\hermes"
' 防御性覆盖:确保 hermes.exe gateway start 拉起的 gateway 也能解析 dual_agent。
' 根因修复以 multiagent.yaml 的 dual_agent_root 为主来源,这里只是冗余保险。
environment.Item("AI_AGENT_COLLAB_ROOT") = "C:\ai-agent-collaboration"

commandLine = """C:\Users\<WINDOWS_USER>\AppData\Local\hermes\hermes-agent\venv\Scripts\hermes.exe"" gateway start"
exitCode = shell.Run(commandLine, 0, True)

WScript.Quit exitCode
