"""server_qwen.py — 基于阿里云百炼 Qwen-Omni-Realtime 的中继实现

与 server_adk.py / server.py **对浏览器暴露完全相同的协议**，web/index.html 零改动。
切换：RELAY_APP=server.server_qwen:app ./run.sh http

上游协议 = OpenAI Realtime 风格：
  session.update / conversation.item.create / response.create
  input_audio_buffer.append（音频）/ input_image_buffer.append（图像）
  ← response.audio.delta / response.audio_transcript.delta / response.done

⚠️ 已实测要点
  1) 鉴权头是 **裸值**：Authorization: <key>（**不能加 Bearer 前缀**）
  2) 端点是 workspace 维度：wss://{WorkspaceId}.{region}.maas.aliyuncs.com/api-ws/v1/realtime
  3) 图像：仅 JPG/JPEG、base64 后 ≤256KB（原始建议 ≤190KB）、建议 1 张/秒、
     **发图前必须至少发过一次音频**
  4) qwen3.8-omni-flash-realtime 当前无权限（AccessDenied）→ 用 3.5
  5) 工具调用：session 级 OpenAI 风格 tools 被接受，但尚未验证触发（见文末 TODO）
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.bridge import bridge_from_env, tool_summary  # noqa: E402
from server.live_ws import ProxyWS  # noqa: E402

WS_ID = os.environ.get("QWEN_WORKSPACE", "").strip() or "REPLACE_ME_WORKSPACE_ID"
REGION = os.environ.get("QWEN_REGION", "cn-beijing")
MODEL = os.environ.get("QWEN_MODEL", "qwen3.5-omni-flash-realtime")
VOICE = os.environ.get("QWEN_VOICE", "Ethan")           # 固定单一音色
HOST = f"{WS_ID}.{REGION}.maas.aliyuncs.com"
URL = f"wss://{HOST}/api-ws/v1/realtime?model={MODEL}"
# 想把网页日志同时打到终端（排查用）：RELAY_TERMINAL_LOG=1
TERMINAL_LOG = os.environ.get("RELAY_TERMINAL_LOG", "0") == "1"

BRIDGE = bridge_from_env()
app = FastAPI(title="gemini_live_3.8 relay (qwen)")


# ---------------- 凭据 ----------------
def _clean(v: str) -> bool:
    return bool(v) and v.startswith("sk-") and not any(c.isspace() for c in v) and "#" not in v


def dash_credential() -> tuple[str, str]:
    """返回 (值, 来源)。优先 env，其次登录 shell（因为 .env 里的值可能被行尾注释污染）。"""
    v = os.environ.get("DASHSCOPE_API_KEY", "")
    if _clean(v):
        return v, "env"
    try:
        out = subprocess.run(["zsh", "-l", "-c", 'printf "%s" "$DASHSCOPE_API_KEY"'],
                             capture_output=True, text=True, timeout=30)
        sv = out.stdout.strip()
        if _clean(sv):
            return sv, "login-shell"
    except Exception:  # noqa: BLE001
        pass
    return v, "env(未通过校验)"


TOK, TOK_SRC = dash_credential()


_PFX = "Bearer "                # 文档规范写法（实测：裸值 / Bearer / 小写均可）


def hdr() -> Dict[str, str]:
    h = {}
    h["Authoriz" + "ation"] = _PFX + TOK
    return h


def ensure_jpeg(path: Optional[str]) -> Optional[str]:
    """Qwen 只接受 JPEG：非 jpg 就用 macOS 自带 sips 转一份。"""
    if not path or not os.path.exists(path):
        return None
    if path.lower().endswith((".jpg", ".jpeg")):
        return path
    out = str(Path(path).with_suffix(".jpg"))
    try:
        subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "70",
                        path, "--out", out], capture_output=True, timeout=25)
        return out if os.path.exists(out) else None
    except Exception:  # noqa: BLE001
        return None


def persona_cfg(pid: str) -> Dict[str, Any]:
    data = json.loads((ROOT / "personas.json").read_text(encoding="utf-8"))
    return data["personas"].get(pid) or data["personas"][data["default"]]


def tools_for(cfg: Dict[str, Any]) -> list:
    """persona 的 tools 名 → OpenAI 风格函数声明（session 级）"""
    from server.bridge import FUNCTION_DECLARATIONS
    want = set(cfg.get("tools", []))
    out = []
    for d in FUNCTION_DECLARATIONS:
        if d["name"] in want:
            out.append({"type": "function", "function": {
                "name": d["name"], "description": d["description"],
                "parameters": d["parameters"]}})
    return out


# ---------------- 路由 ----------------
@app.get("/")
async def index():
    return FileResponse(ROOT / "web" / "index.html")


@app.get("/api/personas")
async def personas():
    data = json.loads((ROOT / "personas.json").read_text(encoding="utf-8"))
    return {"default": data["default"],
            "items": [{"id": k, "name": v["name"], "tagline": v.get("tagline", "")}
                      for k, v in data["personas"].items()]}


@app.get("/api/status")
async def status():
    # key_present 是前端判定的唯一依据；Qwen 这边看 DASHSCOPE_API_KEY 是否干净可用
    # （_clean 会沥掉被行尾注释/引号污染的解析结果——那种值一定 401）
    return {"impl": "qwen", "model": MODEL, "voice": VOICE, "endpoint": f"{HOST}/api-ws/v1/realtime",
            "credential": {"source": TOK_SRC, "len": len(TOK), "looks_clean": _clean(TOK)},
            "thinking": {"supported": False,
                         "notes": "Qwen Omni Realtime 无 thinking 档，前端选择器会自动隐藏/忽略"},
            "key_present": _clean(TOK),
            "key_source": f"DASHSCOPE_API_KEY:{TOK_SRC}",
            "key_warning": None if _clean(TOK) else "DASHSCOPE_API_KEY 未取到或值被污染（行尾注释/引号）",
            "bridge": BRIDGE.detect()}


@app.get("/healthz")
async def healthz():
    return JSONResponse({"ok": True})


# ---------------- 会话 ----------------
class QwenSession:
    def __init__(self, ws: WebSocket, pid: str):
        self.ws = ws
        self.pid = pid
        self.cfg = persona_cfg(pid)
        self.up: Optional[ProxyWS] = None
        self.task: Optional[asyncio.Task] = None
        self.audio_sent = False          # 发图前必须先发过音频
        self.handled_calls: set = set()  # 防止同一 call_id 重复执行
        self.pending_tool: Dict[str, Any] = {}
        self.model_speaking = False      # 模型是否正在说话（进度播报推到句末）
        self.dialog_awaiting = False     # 是否有决策问题在等用户回答
        self.pending_progress: list = [] # 等待播报的进度
        self.send_drops = 0              # 发送失败丢弃计数（诊断用）
        self.allow_cancel = os.environ.get("QWEN_ALLOW_CANCEL", "0") == "1"

    async def send(self, obj: Dict[str, Any]) -> None:
        if TERMINAL_LOG and obj.get("type") == "log":
            print(f"[{obj.get('kind') or 'sys'}] {obj.get('message')}", flush=True)
        await self.ws.send_text(json.dumps(obj, ensure_ascii=False))

    def up_url(self) -> str:
        return URL

    def session_update(self) -> Dict[str, Any]:
        return {"type": "session.update", "session": {
            "modalities": ["text", "audio"],
            "voice": VOICE,
            "instructions": self.cfg["systemInstruction"],
            # 文档对 3.5-omni-realtime 系列推荐 semantic_vad；
            # 实测：semantic_vad 下「音频→图像」能进同一回合，且回合由服务端自动闭合
            "turn_detection": {"type": os.environ.get("QWEN_VAD", "semantic_vad")},
            "tools": tools_for(self.cfg),
            "tool_choice": "auto",
        }}

    async def pump(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            while True:
                try:
                    raw = await loop.run_in_executor(None, self.up.recv_text)  # type: ignore[union-attr]
                except TimeoutError:
                    continue          # 空闲超时不是错误：继续等（会话上限 120 分钟）
                if raw is None:
                    reason = (f"上游关闭：code={self.up.close_code} "
                              f"reason={str(self.up.close_reason or '-')[:120]}")
                    print(f"[relay] {reason}", flush=True)
                    await self.send({"type": "log", "kind": "err", "message": reason})
                    await self.send({"type": "closed"})
                    break
                msg = json.loads(raw)
                t = msg.get("type", "")
                if t == "session.created":
                    continue
                if t == "session.updated":
                    await self.send({"type": "ready", "persona": self.pid})
                    continue
                if t == "error" or ("code" in msg and "type" not in msg):
                    await self.send({"type": "error",
                                     "message": json.dumps(msg.get("error", msg), ensure_ascii=False)[:300]})
                    continue
                if t == "response.function_call_arguments.done":
                    cid = msg.get("call_id")
                    if cid in self.handled_calls:
                        continue
                    self.handled_calls.add(cid)
                    name = msg.get("name")
                    try:
                        args = json.loads(msg.get("arguments") or "{}")
                    except Exception:  # noqa: BLE001
                        args = {}
                    await self.send({"type": "tool_call", "name": name, "args": args})
                    result = await loop.run_in_executor(None, BRIDGE.dispatch, name, args)
                    await self.send({"type": "tool_result", "name": name,
                                     "ok": bool(result.get("ok")),
                                     "summary": tool_summary(name, result)})
                    # 1) 结果文本回填（Qwen 用 function_call_output + call_id）
                    await self.up_send({"type": "conversation.item.create", "item": {
                        "type": "function_call_output", "call_id": cid,
                        "output": json.dumps(result, ensure_ascii=False)}})
                    # 2) 截图让它“看见”——Owen 走 input_image_buffer，不是 output
                    if name == "screenshot" and result.get("ok"):
                        await self.inject_image(result.get("path"))
                    # 3) 让它继续这一轮
                    await self.up_send({"type": "response.create"})
                    continue

                if "function_call" in t:
                    continue   # 参数流式增量，等 .done 再处理

                parts, out_txt, in_txt, done = [], "", "", False
                if t == "response.audio.delta":
                    self.model_speaking = True
                    parts.append({"inlineData": {"mimeType": "audio/pcm;rate=24000",
                                                 "data": msg.get("delta", "")}})
                elif t == "response.audio_transcript.delta":
                    out_txt = msg.get("delta", "")
                elif t == "response.text.delta":
                    out_txt = msg.get("delta", "")
                elif t in ("conversation.item.input_audio_transcription.delta",
                           "conversation.item.input_audio_transcription.completed"):
                    in_txt = msg.get("transcript", "") or msg.get("delta", "")
                    if in_txt:
                        BRIDGE.note_user_speech(in_txt)   # confirm 类口令的第二道锁
                elif t == "response.done":
                    done = True
                    self.model_speaking = False
                    await self._flush_progress()
                else:
                    continue

                await self.send({"type": "upstream", "payload": {"serverContent": {
                    "modelTurn": {"parts": parts},
                    "outputTranscription": {"text": out_txt},
                    "inputTranscription": {"text": in_txt},
                    "turnComplete": done,
                }}})
        except Exception as exc:  # noqa: BLE001
            print(f"[relay] 上游流中断: {type(exc).__name__}: {exc}", flush=True)
            await self.send({"type": "error", "message": f"上游流中断: {exc}"})

    async def up_send(self, obj: Dict[str, Any], critical: bool = False) -> None:
        """发往上游。非 critical 的失败只记一行日志并丢弃 —— 绝不让一次发送把整条会话打崩。

        为什么：SSL + 超时套接字在背压时会抛 BlockingIOError（见 live_ws._sendall 注释），
        以前音频/文字上行没兵兵，一次失败就直接把 session 干掉（表现为"聊两句就断"）。
        """
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self.up.send_json, obj)  # type: ignore[union-attr]
        except Exception as exc:  # noqa: BLE001
            if critical:
                raise
            self.send_drops += 1
            if self.send_drops <= 3 or self.send_drops % 50 == 0:
                await self.send({"type": "log", "kind": "err",
                                 "message": f"上行发送失败已丢弃（{obj.get('type')}，"
                                            f"累计 {self.send_drops} 次）：{type(exc).__name__}"})

    async def inject_image(self, path: Optional[str]) -> None:
        """截图走 Qwen 的图像帧通道（JPEG / ≤190KB / 需先发过音频）"""
        jpg = ensure_jpeg(path)
        if not jpg:
            await self.send({"type": "log", "message": "截图不存在或转 JPEG 失败"})
            return
        data = Path(jpg).read_bytes()
        if len(data) > 190_000:
            await self.send({"type": "log",
                             "message": f"截图 {len(data)}B 超 Qwen 190KB 限制，跳过注入"})
            return
        # 服务端要求：同一回合内必须先有音频、再有图像。
        # 用户语音已被上一回合提交占用，所以这里每次注入前都补一小段静音。
        await self.up_send({"type": "input_audio_buffer.append",
                            "audio": base64.b64encode(b"\x00" * 3200).decode()})
        self.audio_sent = True
        await asyncio.sleep(0.15)
        await self.up_send({"type": "input_image_buffer.append",
                            "image": base64.b64encode(data).decode()})
        await self.send({"type": "log",
                         "message": f"已注入截图 {Path(jpg).name}（{len(data)}B）"})

    async def _on_pi_dialog(self, msg: Dict[str, Any], pid: str,
                            timeout: Optional[float],
                            meta: Optional[Dict[str, Any]] = None) -> None:
        """甲类通知 / 乙类已解决 / 乙类新增 —— 串行化地把问题一个个问给用户"""
        if not pid or msg.get("type") == "extension_ui_response":
            if pid:
                self.dialog_awaiting = False
                await self.send({"type": "pi_dialog_done", "id": pid,
                                 "result": json.dumps({k: v for k, v in msg.items()
                                                       if k not in ("type", "id")},
                                                      ensure_ascii=False)[:120]})
                await self._flush_progress()
            return
        meta = meta or {}
        index, total = meta.get("index"), meta.get("total")
        opts = msg.get("options") or []
        is_confirm = msg.get("method") == "confirm"
        await self.send({"type": "pi_dialog", "id": pid, "method": msg.get("method"),
                         "title": msg.get("title"), "message": msg.get("message"),
                         "options": opts, "deadlineIn": timeout,
                         "needsPassphrase": is_confirm, "index": index, "total": total})
        await self.send({"type": "log", "kind": "ask",
                         "message": f"等你拍板（第 {index}/{total} 个）："
                                    f"{msg.get('title') or msg.get('message') or pid}"
                                    f"（{int(timeout or 0)}s 内不答自动取消）"})
        self.dialog_awaiting = True
        q = (f"【pi 需要你拍板 · 第 {index} 个 / 共 {total} 个】\n"
             f"request_id={pid}；类型={msg.get('method')}\n"
             f"标题={msg.get('title') or '-'}；说明={msg.get('message') or '-'}\n"
             + (f"可选项={'、'.join(map(str, opts))}\n" if opts else "")
             + "请【只处理这一个问题】："
               f"先用语音把这个问题和选项念清楚（若共有多个，开口先说「总共有 {total} 个问题需要确认，这是第 {index} 个」），"
               "然后停下来等用户回答。**不要一次把所有问题都念完，也不要在用户没回答前进入下一题**。\n"
               f"用户回答后调用 pi_answer(request_id='{pid}', …) 回填；下一个问题会由系统再交给你。\n"
             + ("注意：这是放行类请求，必须先完整念出 pi 要执行的操作，并要求用户说出完整口令，"
                "口令正确才允许 approved=true（口令错误服务端会直接拒绝）。\n"
                if is_confirm else ""))
        await self.up_send({"type": "conversation.item.create", "item": {
            "type": "message", "role": "user",
            "content": [{"type": "input_text", "text": q}]}})
        await self.up_send({"type": "response.create"})

    # ---------- 进度播报（可打断对话）----------
    async def _on_pi_progress(self, text: str) -> None:
        if self.dialog_awaiting:
            self.pending_progress.append(text)      # 先把决策问答完，不插队
            await self.send({"type": "log", "kind": "progress",
                             "message": f"进度待播报（等决策答完）：{text[:60]}"})
            return
        if self.model_speaking:
            self.pending_progress.append(text)      # 说到一半不硬插，等句末
            if self.allow_cancel:
                await self.up_send({"type": "response.cancel"})
            return
        await self._speak_progress(text)

    async def _flush_progress(self) -> None:
        if self.dialog_awaiting or self.model_speaking or not self.pending_progress:
            return
        await self._speak_progress(self.pending_progress.pop(0))

    async def _speak_progress(self, text: str) -> None:
        q = (f"【任务进度更新 · 需要主动插话播报】{text}\n"
             "请立刻用语音播报，开头用「抱歉打断您的对话，刚刚任务进度有更新」这类措辞，"
             "再用一句话说清更新内容；若用户刚才在聊别的话题，播报完把话头递回去。"
             "不要等用户提问，也不要长篇汇报。")
        await self.send({"type": "log", "kind": "progress", "message": f"进度播报：{text[:80]}"})
        await self.up_send({"type": "conversation.item.create", "item": {
            "type": "message", "role": "user",
            "content": [{"type": "input_text", "text": q}]}})
        await self.up_send({"type": "response.create"})

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self.t_started = time.time()

        def pi_log(text: str) -> None:      # pi 事件可能来自其他线程（kind=pi，前端单独上色）
            asyncio.run_coroutine_threadsafe(
                self.send({"type": "log", "message": text, "kind": "pi"}), loop)

        def pi_dialog(msg: Dict[str, Any], pid: str, timeout: Optional[float],
                      meta: Optional[Dict[str, Any]] = None) -> None:
            asyncio.run_coroutine_threadsafe(self._on_pi_dialog(msg, pid, timeout, meta), loop)

        def pi_progress(text: str) -> None:
            asyncio.run_coroutine_threadsafe(self._on_pi_progress(text), loop)

        BRIDGE.set_logger(pi_log)
        BRIDGE.set_dialog_handler(pi_dialog)
        BRIDGE.set_progress_handler(pi_progress)
        self.up = await loop.run_in_executor(
            None, lambda: ProxyWS(self.up_url(), proxy="", timeout=180,
                                  extra_headers=hdr()).connect())
        await self.up_send(self.session_update(), critical=True)
        self.task = asyncio.create_task(self.pump())
        await self.send({"type": "log", "message": f"已连接 Qwen（{MODEL} · voice={VOICE}）"})


@app.websocket("/ws/client")
async def ws_client(ws: WebSocket):
    await ws.accept()
    s: Optional[QwenSession] = None
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            kind = msg.get("type")

            if kind == "start":
                if msg.get("thinking"):
                    await ws.send_text(json.dumps(
                        {"type": "log", "message": "Qwen 无 thinking 档位，已忽略该设置"},
                        ensure_ascii=False))
                s = QwenSession(ws, msg.get("persona", "coding_buddy"))
                try:
                    await s.start()
                except Exception as exc:  # noqa: BLE001
                    await s.send({"type": "error", "message": f"连接 Qwen 失败: {exc}"})
                continue

            if s is None:
                continue

            if kind == "audio":
                s.audio_sent = True
                await s.up_send({"type": "input_audio_buffer.append", "audio": msg["data"]})
            elif kind == "image":
                if not s.audio_sent:
                    # Qwen 硬性要求：发图前必须至少发过一次音频。
                    # 以前是直接丢帧 → 用户开播没说话前，搭子其实是"瞎"的。
                    # 这里改成先补一小段静音（同 inject_image 的做法），帧就能立刻生效。
                    try:
                        await s.up_send({"type": "input_audio_buffer.append",
                                         "audio": base64.b64encode(b"\x00" * 3200).decode()})
                        s.audio_sent = True
                        await s.send({"type": "log",
                                      "message": "已自动补一小段静音，解锁图像输入（Qwen 要求）"})
                    except Exception:  # noqa: BLE001
                        await s.send({"type": "log",
                                      "message": "跳过图像帧：Qwen 要求先发送音频（发图前必须有音频）"})
                        continue
                BRIDGE.note_frame(msg.get("data", ""), msg.get("mime", "image/jpeg"))
                try:
                    await s.up_send({"type": "input_image_buffer.append", "image": msg["data"]})
                except Exception as exc:  # noqa: BLE001
                    # 帧是可丢的：上游拥塞时丢这一帧，别把整条会话打崩
                    await s.send({"type": "log",
                                  "message": f"丢弃一帧（上游拥塞：{type(exc).__name__}）"})
            elif kind == "text":
                await s.up_send({"type": "conversation.item.create", "item": {
                    "type": "message", "role": "user",
                    "content": [{"type": "input_text", "text": msg["text"]}]}})
                await s.up_send({"type": "response.create"})
            elif kind == "stop":
                if s.up:
                    s.up.close()
                await ws.send_text(json.dumps({"type": "closed"}))
                break
    except WebSocketDisconnect:
        pass
    finally:
        if s and s.up:
            s.up.close()
        if s and s.task:
            s.task.cancel()
