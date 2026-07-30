' cc-connect Launcher - starts cc-connect at Windows boot (Stage 2)
' Uses pythonw.exe (no console window) to run the launcher script, which
' loads .env tokens and starts cc-connect.exe directly (detached, bypassing
' the npm wrapper that would overwrite our patched binary).
Option Explicit
Dim sh, env
Set sh = CreateObject("WScript.Shell")
Set env = sh.Environment("PROCESS")
env.Item("PYTHONIOENCODING") = "utf-8"
' pythonw.exe = no console window; the launcher itself starts cc-connect
' with DETACHED_PROCESS so it survives independently.  Window mode 0 = hidden.
sh.Run """C:\Users\<WINDOWS_USER>\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\pythonw.exe"" ""C:\Users\<WINDOWS_USER>\.cc-connect\cc_connect_autostart.py""", 0, False
