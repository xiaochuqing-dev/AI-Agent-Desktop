"""cc-connect autostart launcher (Stage 1.5).

Reads bot tokens from bot-tokens.env (ASCII path, avoids Chinese-path issues
in cmd.exe), sets them as process environment, and launches cc-connect.

Invoked at Windows startup by CcConnect_Autostart.vbs.
"""

import os
import subprocess
import sys
from pathlib import Path

CC_HOME = Path(r"C:\Users\<WINDOWS_USER>\.cc-connect")
ENV_FILE = CC_HOME / "bot-tokens.env"
CONFIG = CC_HOME / "config.toml"
LOG = CC_HOME / "logs" / "autostart.log"
# Stage 2: use the .exe DIRECTLY, not the npm .cmd wrapper.  The wrapper's
# run.js checks `cc-connect --version` and re-downloads the official binary
# when it doesn't match "1.4.1", which would overwrite our patched build
# (P0 isDirectedAtBot + Headers fix).  The exe bypasses that check.
CC_CONNECT = Path(os.environ.get("APPDATA", "")) / "npm" / "node_modules" / "cc-connect" / "bin" / "cc-connect.exe"


def load_env(path: Path) -> dict:
    env = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        if key:
            env[key] = val
    return env


def main() -> int:
    LOG.parent.mkdir(parents=True, exist_ok=True)

    tokens = load_env(ENV_FILE)
    if "CLAUDE_CODE_BOT_TOKEN" not in tokens or "CODEX_BOT_TOKEN" not in tokens:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"[autostart] bot tokens missing in {ENV_FILE}\n")
        return 1

    env = os.environ.copy()
    env.update(tokens)
    env.pop("CLAUDECODE", None)  # cc-connect requirement: claude CLI can't be child of claude

    # A2 黑窗修复（层2）：给 daemon 一个隐藏控制台，让 cc-connect spawn 的
    # claude.exe/codex.exe 等孙进程继承它，不再各自弹可见黑窗。
    # 旧方案用 DETACHED_PROCESS（无控制台），导致 daemon 内部 spawn 的每个 console
    # 子进程都被 Windows 新建可见控制台 -> 滞留黑窗（AppData 路径标题）。
    # 改用 CREATE_NEW_CONSOLE + STARTUPINFO.wShowWindow=SW_HIDE：daemon 拥有一个
    # 隐藏控制台，孙进程继承该隐藏控制台，不弹窗。等价于官方 daemon 模式的
    # powershell -WindowStyle Hidden 思路，但不引入 powershell 中间层。

    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"[autostart] launching cc-connect (hidden-console) with {len(tokens)} env vars\n")

    # CREATE_NEW_CONSOLE (0x00000010) + 隐藏窗口（SW_HIDE=0）
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0  # SW_HIDE
    proc = subprocess.Popen(
        [str(CC_CONNECT), "--config", str(CONFIG), "--force"],
        env=env,
        cwd=str(CC_HOME),
        stdout=open(LOG, "ab"),
        stderr=subprocess.STDOUT,
        startupinfo=si,
        creationflags=0x00000010,  # CREATE_NEW_CONSOLE（隐藏，供孙进程继承）
    )
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"[autostart] cc-connect started pid={proc.pid} exe={CC_CONNECT}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
