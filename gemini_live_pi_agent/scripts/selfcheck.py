"""selfcheck.py — 无框架冒烟测试：验证 本机 -> 代理 -> Gemini Live 的文本会话链路。

不需要 fastapi/uvicorn，只用 stdlib。
用法：  python3 scripts/selfcheck.py
成功输出：  收到模型文本回复（说明 setup / clientContent / serverContent 全链路通）
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.live_ws import ProxyWS  # noqa: E402

MODEL = os.environ.get("LIVE_MODEL", "models/gemini-3.8-live")
WS_BASE = ("wss://generativelanguage.googleapis.com/ws/"
           "google.ai.generativelanguage.v1alpha.GenerativeService.BidiGenerateContent")


def env_file() -> dict:
    out = {}
    p = os.path.expanduser(os.environ.get("RELAY_ENV_FILE")
                           or "~/.config/gemini-live-relay/.env")
    if os.path.exists(p):
        for line in open(p):
            m = re.match(r"(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)", line.strip())
            if m:
                out[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return out


def main() -> int:
    key = os.environ.get("GEMINI_API_KEY") or env_file().get("GEMINI_API_KEY")
    if not key:
        print("✗ 未找到 GEMINI_API_KEY")
        return 2
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    print(f"模型: {MODEL}")
    print(f"代理: {proxy or '(直连)'}")
    print(f"Key : 已加载（{len(key)} 字符，不打印）")

    t0 = time.time()
    try:
        ws = ProxyWS(f"{WS_BASE}?key={key}", proxy=proxy, timeout=20).connect()
    except Exception as exc:  # noqa: BLE001
        print(f"✗ 连接失败: {exc}")
        return 1
    print(f"✓ WebSocket 已连接（{time.time()-t0:.2f}s）")

    # 注意：gemini-3.8-live 是**音频输出**模型，TEXT 模态不被支持；
    # 文字通过 outputAudioTranscription 拿到。
    ws.send_json({"setup": {"model": MODEL,
                            "generationConfig": {"responseModalities": ["AUDIO"]},
                            "outputAudioTranscription": {}}})

    # 1) 必须先等 setupComplete（提前发内容会被上游直接关闭）
    setup_ok = False
    deadline = time.time() + 20
    while time.time() < deadline and not setup_ok:
        raw = ws.recv_text()
        if raw is None:
            print(f"✗ setup 阶段上游关闭: code={ws.close_code} reason={ws.close_reason!r}")
            return 1
        msg = json.loads(raw)
        if "setupComplete" in msg:
            setup_ok = True
            print("✓ setupComplete")
        elif "error" in msg:
            print("⚠ 上游报错:", json.dumps(msg, ensure_ascii=False)[:500])
        elif "goAway" in msg:
            print("⚠ goAway:", json.dumps(msg, ensure_ascii=False)[:200])
    if not setup_ok:
        print("✗ 20s 内未收到 setupComplete")
        return 1

    # 2) 再发一句文本，等回复
    ws.send_json({"clientContent": {
        "turns": [{"role": "user",
                   "parts": [{"text": "只回一句简短中文，确认链路正常。"}]}],
        "turnComplete": True}})

    texts, audio_bytes = [], 0
    deadline = time.time() + 30
    while time.time() < deadline:
        raw = ws.recv_text()
        if raw is None:
            print(f"⚠ 上游关闭: code={ws.close_code} reason={ws.close_reason!r}")
            break
        msg = json.loads(raw)
        sc = msg.get("serverContent") or {}
        if (sc.get("outputTranscription") or {}).get("text"):
            texts.append(sc["outputTranscription"]["text"])
        for part in ((sc.get("modelTurn") or {}).get("parts") or []):
            if part.get("text"):
                texts.append(part["text"])
            d = part.get("inlineData") or {}
            if (d.get("mimeType") or "").startswith("audio/") and d.get("data"):
                audio_bytes += len(d["data"]) * 3 // 4
        if sc.get("turnComplete") or audio_bytes or texts:
            break

    ws.close()
    if not setup_ok:
        print("✗ 没有收到 setupComplete")
        return 1
    print(f"✓ 音频下行 {audio_bytes} 字节" + (f" / 转写: {' '.join(texts).strip()[:160]}" if texts else ""))
    if audio_bytes or texts:
        print("✓ 链路全通（setup -> clientContent -> 音频下行 serverContent）")
        return 0
    print("⚠ setup 成功，但 30s 内未拿到音频/转写")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
