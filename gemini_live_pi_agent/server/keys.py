"""keys.py — 凭据解析（两个中继实现共用，避免各写一份导致状态口径不一致）

为什么需要这层：
  - server.py（裸 WS 版）自己拼 URL，所以 Key 可以「环境变量 或 RELAY_ENV_FILE」二选一；
  - server_adk.py（ADK 版）把 Key 交给 google-genai SDK，而 SDK **只读环境变量**
    （GEMINI_API_KEY / GOOGLE_API_KEY / GOOGLE_GENAI_API_KEY），不会读 .env 文件。
  两者口径不同，所以这里把「环境变量」和「文件」分开暴露：
    env_key()   → 真正会被 SDK 用到的那个
    file_key()  → 只对裸 WS 版有效的兜底
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, Optional, Tuple

ENV_FILE = Path(os.environ.get("RELAY_ENV_FILE")
                or (Path.home() / ".config" / "gemini-live-relay" / ".env")).expanduser()
NAMES = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY")


def load_env_file(path: Optional[Path] = None) -> Dict[str, str]:
    """从 RELAY_ENV_FILE（默认 ~/.config/gemini-live-relay/.env）读取凭据。"""
    out: Dict[str, str] = {}
    p = path or ENV_FILE
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            m = re.match(r"(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)", line.strip())
            if m:
                out[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return out


def env_key() -> Optional[Tuple[str, str]]:
    """返回 (key, 变量名)；环境变量里没有则 None。SDK 实际用的就是它。"""
    for n in NAMES:
        v = os.environ.get(n)
        if v:
            return v, n
    return None


def file_key() -> Optional[Tuple[str, str]]:
    """返回 (key, 变量名)；RELAY_ENV_FILE 里没有则 None。"""
    data = load_env_file()
    for n in NAMES:
        v = data.get(n)
        if v:
            return v, n
    return None


def resolve_key() -> Optional[Tuple[str, str]]:
    """环境变量优先，其次 .env 文件。返回 (key, 来源标签)。"""
    hit = env_key()
    if hit:
        return hit[0], f"env:{hit[1]}"
    hit = file_key()
    if hit:
        return hit[0], f"file:{ENV_FILE.name}:{hit[1]}"
    return None


def api_key() -> Optional[str]:
    """裸 WS 版用：环境变量或 .env 都行。"""
    hit = resolve_key()
    return hit[0] if hit else None


def status_fields() -> Dict[str, object]:
    """给 /api/status 用的统一字段（不含 Key 本体，只报有无与来源）。

    key_present / key_source → 两个实现共同的真实口径（环境变量）
    key_in_env_file          → 仅 .env 里有，裸 WS 版可用、ADK 版会失败
    """
    env = env_key()
    fil = file_key()
    if env:
        return {"key_present": True, "key_source": f"env:{env[1]}",
                "key_in_env_file": bool(fil)}
    if fil:
        return {"key_present": False, "key_source": None,
                "key_in_env_file": True,
                "key_warning": f"{fil[1]} 只存在于 {ENV_FILE}，未导出到进程环境"}
    return {"key_present": False, "key_source": None, "key_in_env_file": False}
