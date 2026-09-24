"""server.py — 本机中继服务（浏览器瘦客户端 <-> Gemini Live API）

用法：
    python -m uvicorn server.server:app --host 0.0.0.0 --port 8000          # 纯 HTTP（直连 IP）
    python -m uvicorn server.server:app --host 0.0.0.0 --port 8443 \
        --ssl-keyfile certs/key.pem --ssl-certfile certs/cert.pem          # HTTPS

端点：
    GET  /                 瘦客户端页面
    GET  /api/personas     可选 persona 列表
    GET  /api/status       服务端 + pi 后端状态
    WS   /ws/client        浏览器 <-> 服务端（JSON 文本帧，音频走 base64）

设计：
    - 服务端持有 API Key / 会话状态 / pi 桥接；浏览器只采集与播放。
    - 上游用 server/live_ws.py（自带代理隧道），不依赖 ws 库的代理支持。
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.bridge import (FUNCTION_DECLARATIONS, bridge_from_env,  # noqa: E402
                           normalize_live_model, resolve_live_model, thinking_catalog,
                           tool_summary)
from server.keys import api_key, load_env_file, status_fields  # noqa: E402
from server.live_ws import ProxyWS  # noqa: E402

MODEL = os.environ.get("LIVE_MODEL", "models/gemini-3.8-live")
# 固定单一音色：不做切换，保证每次/整段会话前后一致。
# 如需换：改这里或设环境变量 LIVE_VOICE。-->
VOICE = os.environ.get("LIVE_VOICE", "Aoede")
# 固定输出语言：防止模型自己漂到英文/日文（实测：不锁语言时会跟随提问语言）
LANGUAGE = os.environ.get("LIVE_LANGUAGE", "cmn-CN")
WS_BASE = ("wss://generativelanguage.googleapis.com/ws/"
           "google.ai.generativelanguage.v1alpha.GenerativeService.BidiGenerateContent")
INPUT_AUDIO_MIME = "audio/pcm;rate=16000"
# 想把网页日志同时打到终端（排查用）：RELAY_TERMINAL_LOG=1
TERMINAL_LOG = os.environ.get("RELAY_TERMINAL_LOG", "0") == "1"

app = FastAPI(title="gemini_live_3.8 relay")
BRIDGE = bridge_from_env()


# ---------------- 配置 ----------------
def proxy_url() -> Optional[str]:
    return os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")


def persona_cfg(pid: str) -> Dict[str, Any]:
    data = json.loads((ROOT / "personas.json").read_text(encoding="utf-8"))
    return data["personas"].get(pid) or data["personas"][data["default"]]


# ---------------- 路由 ----------------
@app.get("/")
async def index():
    return FileResponse(ROOT / "web" / "index.html")


@app.get("/api/personas")
async def personas():
    data = json.loads((ROOT / "personas.json").read_text(encoding="utf-8"))
    return {
        "default": data["default"],
        "items": [{"id": k, "name": v["name"], "tagline": v.get("tagline", "")}
                  for k, v in data["personas"].items()],
    }


@app.get("/api/status")
async def status():
    return {
        **status_fields(),
        "impl": "raw",
        "model": MODEL,
        "voice": VOICE,
        "language": LANGUAGE,
        "thinking": thinking_catalog(),
        "proxy": proxy_url(),
        "bridge": BRIDGE.detect(),
    }


# ---------------- 会话 ----------------
class Session:
    def __init__(self, ws: WebSocket, pid: str, thinking: Optional[str] = None):
        self.ws = ws
        self.pid = pid
        self.lv = resolve_live_model(thinking)      # 前端选的推理档位 → 模型 + thinkingConfig
        self.cfg = persona_cfg(pid)
        self.up: Optional[ProxyWS] = None
        self.task: Optional[asyncio.Task] = None
        self.model_speaking = False
        self.dialog_awaiting = False
        self.pending_progress: list = []
        self.send_drops = 0

    def url(self) -> str:
        return f"{WS_BASE}?key={api_key()}"

    def setup_msg(self) -> Dict[str, Any]:
        tools = [d for d in FUNCTION_DECLARATIONS if d["name"] in self.cfg.get("tools", [])]
        gen: Dict[str, Any] = {
            "responseModalities": ["AUDIO"],
            # 音色：prebuiltVoiceConfig.voiceName
            "speechConfig": {"voiceConfig": {
                "prebuiltVoiceConfig": {"voiceName": VOICE}},
                "languageCode": LANGUAGE},
        }
        if self.lv.get("thinkingConfig"):
            gen["thinkingConfig"] = self.lv["thinkingConfig"]
        return {
            "setup": {
                "model": normalize_live_model(self.lv["model"]),
                "generationConfig": gen,
                "systemInstruction": {"parts": [{"text": self.cfg["systemInstruction"]}]},
                "tools": [{"functionDeclarations": tools}] if tools else [],
                # 文字转写（setup 层级字段，不是 generationConfig 里的）
                "outputAudioTranscription": {},
                "inputAudioTranscription": {},
                # 长会话必需（否则音视频会话约 2 分钟断连）
                "contextWindowCompression": {"slidingWindow": {}},
            }
        }

    async def send_local(self, obj: Dict[str, Any]) -> None:
        if TERMINAL_LOG and obj.get("type") == "log":
            print(f"[{obj.get('kind') or 'sys'}] {obj.get('message')}", flush=True)
        await self.ws.send_text(json.dumps(obj, ensure_ascii=False))

    # ---- 上游 -> 浏览器 ----
    async def pump_upstream(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            while True:
                raw = await loop.run_in_executor(None, self.up.recv_text)  # type: ignore[union-attr]
                if raw is None:
                    reason = (f"上游关闭：code={self.up.close_code} "
                              f"reason={str(self.up.close_reason or '-')[:120]}")
                    print(f"[relay] {reason}", flush=True)
                    await self.send_local({"type": "log", "kind": "err", "message": reason})
                    await self.send_local({"type": "closed"})
                    break
                msg = json.loads(raw)
                if "setupComplete" in msg:
                    await self.send_local({"type": "ready", "persona": self.pid})
                    continue
                if "toolCall" in msg:
                    await self.handle_tool_call(msg["toolCall"])
                    continue
                sc = msg.get("serverContent") or {}
                heard = (sc.get("inputTranscription") or {}).get("text") or ""
                if heard.strip():
                    BRIDGE.note_user_speech(heard)   # confirm 类口令的第二道锁
                has_audio = any((p.get("inlineData") or {}).get("data")
                                for p in ((sc.get("modelTurn") or {}).get("parts") or []))
                if has_audio:
                    self.model_speaking = True
                if sc.get("turnComplete"):
                    self.model_speaking = False
                    await self._flush_progress()
                await self.send_local({"type": "upstream", "payload": msg})
        except Exception as exc:  # noqa: BLE001
            print(f"[relay] upstream 异常: {type(exc).__name__}: {exc}", flush=True)
            await self.send_local({"type": "error", "message": f"upstream: {exc}"})

    async def handle_tool_call(self, tool_call: Dict[str, Any]) -> None:
        loop = asyncio.get_running_loop()
        responses = []
        for fc in tool_call.get("functionCalls", []):
            name, args, fid = fc.get("name"), fc.get("args", {}), fc.get("id")
            await self.send_local({"type": "tool_call", "name": name, "args": args})
            result = await loop.run_in_executor(None, BRIDGE.dispatch, name, args)
            await self.send_local({"type": "tool_result", "name": name,
                                   "ok": bool(result.get("ok")),
                                   "summary": tool_summary(name, result)})
            responses.append({"id": fid, "name": name, "response": result})
            # 截图类结果：把图片注入会话，让模型"看到"（client content update）
            if name == "screenshot" and result.get("ok") and result.get("path"):
                try:
                    b64 = base64.b64encode(Path(result["path"]).read_bytes()).decode()
                    await self.up_send({  # type: ignore[union-attr]
                        "clientContent": {
                            "turns": [{"role": "user", "parts": [
                                {"inlineData": {"mimeType": "image/png", "data": b64}},
                                {"text": "这是最新的屏幕截图。"},
                            ]}],
                            "turnComplete": True,
                        }
                    })
                except Exception as exc:  # noqa: BLE001
                    await self.send_local({"type": "log", "message": f"inject failed: {exc}"})
        await self.up_send({"toolResponse": {"functionResponses": responses}})  # type: ignore[union-attr]

    async def up_send(self, obj: Dict[str, Any], critical: bool = False) -> None:
        """发往上游。非 critical 的失败只记日志并丢弃，不让一次发送把会话打崩。"""
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self.up.send_json, obj)  # type: ignore[union-attr]
        except Exception as exc:  # noqa: BLE001
            if critical:
                raise
            self.send_drops += 1
            if self.send_drops <= 3 or self.send_drops % 50 == 0:
                await self.send_local({"type": "log", "kind": "err",
                                       "message": f"上行发送失败已丢弃（{obj.get('type')}，"
                                                  f"累计 {self.send_drops} 次）：{type(exc).__name__}"})

    # ---- 主循环 ----
    async def _on_pi_dialog(self, msg: Dict[str, Any], pid: str,
                            timeout: Optional[float],
                            meta: Optional[Dict[str, Any]] = None) -> None:
        if not pid or msg.get("type") == "extension_ui_response":
            if pid:
                self.dialog_awaiting = False
                await self.send_local({"type": "pi_dialog_done", "id": pid,
                                       "result": json.dumps({k: v for k, v in msg.items()
                                                             if k not in ("type", "id")},
                                                            ensure_ascii=False)[:120]})
                await self._flush_progress()
            return
        meta = meta or {}
        index, total = meta.get("index"), meta.get("total")
        opts = msg.get("options") or []
        is_confirm = msg.get("method") == "confirm"
        await self.send_local({"type": "pi_dialog", "id": pid, "method": msg.get("method"),
                               "title": msg.get("title"), "message": msg.get("message"),
                               "options": opts, "deadlineIn": timeout,
                               "needsPassphrase": is_confirm, "index": index, "total": total})
        await self.send_local({"type": "log", "kind": "ask",
                               "message": f"等你拍板（第 {index}/{total} 个）："
                                          f"{msg.get('title') or msg.get('message') or pid}"
                                          f"（{int(timeout or 0)}s 内不答自动取消）"})
        self.dialog_awaiting = True
        q = (f"【pi 需要你拍板 · 第 {index} 个 / 共 {total} 个】request_id={pid}；"
             f"类型={msg.get('method')}；标题={msg.get('title') or '-'}；"
             f"说明={msg.get('message') or '-'}；"
             + (f"可选项={'、'.join(map(str, opts))}；" if opts else "")
             + "请【只处理这一个问题】：先念清本问题和选项"
               f"（若共多个，先说「总共有 {total} 个问题需要确认，这是第 {index} 个」），"
               "然后停下等用户回答；不要一次念完所有问题。"
               f"回答后调用 pi_answer(request_id='{pid}', …) 回填。"
             + ("这是放行类请求，必须先完整念出 pi 要执行的操作，并要求用户说出完整口令。"
                if is_confirm else ""))
        await self.up_send({"clientContent": {
            "turns": [{"role": "user", "parts": [{"text": q}]}], "turnComplete": True}})

    async def _on_pi_progress(self, text: str) -> None:
        if self.dialog_awaiting or self.model_speaking:
            self.pending_progress.append(text)
            return
        await self._speak_progress(text)

    async def _flush_progress(self) -> None:
        if self.dialog_awaiting or self.model_speaking or not self.pending_progress:
            return
        await self._speak_progress(self.pending_progress.pop(0))

    async def _speak_progress(self, text: str) -> None:
        q = (f"【任务进度更新 · 需要主动插话播报】{text}\n"
             "请立刻用语音播报，开头用「抱歉打断您的对话，刚刚任务进度有更新」这类措辞，"
             "再用一句话说清更新内容；若用户刚才在聊别的话题，播报完把话头递回去。")
        await self.send_local({"type": "log", "kind": "progress", "message": f"进度播报：{text[:80]}"})
        await self.up_send({"clientContent": {
            "turns": [{"role": "user", "parts": [{"text": q}]}], "turnComplete": True}})

    async def run(self) -> None:
        loop = asyncio.get_running_loop()

        def pi_log(text: str) -> None:      # pi 事件可能来自其他线程
            asyncio.run_coroutine_threadsafe(
                self.send_local({"type": "log", "message": text, "kind": "pi"}), loop)

        def pi_dialog(msg: Dict[str, Any], pid: str, timeout: Optional[float],
                      meta: Optional[Dict[str, Any]] = None) -> None:
            asyncio.run_coroutine_threadsafe(self._on_pi_dialog(msg, pid, timeout, meta), loop)

        def pi_progress(text: str) -> None:
            asyncio.run_coroutine_threadsafe(self._on_pi_progress(text), loop)

        BRIDGE.set_logger(pi_log)
        BRIDGE.set_dialog_handler(pi_dialog)
        BRIDGE.set_progress_handler(pi_progress)
        self.up = await loop.run_in_executor(
            None, lambda: ProxyWS(self.url(), proxy=proxy_url()).connect()
        )
        await self.up_send(self.setup_msg(), critical=True)
        self.task = asyncio.create_task(self.pump_upstream())
        await self.send_local({"type": "ready", "persona": self.pid,
                               "model": self.lv["model"], "thinking": self.lv["thinking"],
                               "variant": self.lv["variant"]})
        await self.send_local({"type": "log",
                               "message": f"已连接上游（{self.lv['model']} · {self.lv['label']}）"})


@app.websocket("/ws/client")
async def ws_client(ws: WebSocket):
    await ws.accept()
    session: Optional[Session] = None
    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            kind = msg.get("type")

            if kind == "start":
                lv = resolve_live_model(msg.get("thinking"))
                if not lv.get("ok"):
                    await ws.send_text(json.dumps({"type": "error", "message": lv["error"]},
                                                  ensure_ascii=False))
                    continue
                session = Session(ws, msg.get("persona", "coding_buddy"), msg.get("thinking"))
                await session.send_local({"type": "starting", "persona": session.pid,
                                          "model": lv["model"], "label": lv["label"]})
                try:
                    await session.run()
                except Exception as exc:  # noqa: BLE001
                    await session.send_local({"type": "error",
                                              "message": f"启动上游失败: {exc}"})
                continue

            if session is None:
                continue

            if kind == "audio":                       # 上行 PCM16/16k（base64）
                await session.up_send({"realtimeInput": {"audio": {
                    "data": msg["data"], "mimeType": INPUT_AUDIO_MIME}}})
            elif kind == "image":                     # 摄像头帧 / 屏幕帧
                BRIDGE.note_frame(msg.get("data", ""), msg.get("mime", "image/jpeg"))
                try:
                    await session.up_send({"realtimeInput": {"video": {
                        "data": msg["data"], "mimeType": msg.get("mime", "image/jpeg")}}})
                except Exception as exc:  # noqa: BLE001
                    await session.send_local({"type": "log",
                                              "message": f"丢弃一帧（上游拥塞：{type(exc).__name__}）"})
            elif kind == "text":
                await session.up_send({"clientContent": {
                    "turns": [{"role": "user", "parts": [{"text": msg["text"]}]}],
                    "turnComplete": True}})
            elif kind == "stop":
                if session.up:
                    session.up.close()
                await ws.send_text(json.dumps({"type": "closed"}))
                break
    except WebSocketDisconnect:
        pass
    finally:
        if session and session.up:
            session.up.close()
        if session and session.task:
            session.task.cancel()


@app.get("/healthz")
async def healthz():
    return JSONResponse({"ok": True})
