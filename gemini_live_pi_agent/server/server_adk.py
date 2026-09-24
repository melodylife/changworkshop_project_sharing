"""server_adk.py — 基于 Google ADK (google-adk) 的中继实现

与 server.py（裸 WebSocket 版）**对浏览器暴露完全相同的协议**，所以 web/index.html
不用改一行。切换方式见 run.sh 的 RELAY_APP。

ADK 帮我们扛掉的部分：
  - Live API 会话生命周期（run_live 长流）
  - 工具调用：普通 Python 函数 + docstring 即自动生成声明并执行
  - 音频/视频实时帧：LiveRequestQueue.send_realtime
  - 转写、语音配置、上下文压缩、会话恢复：都在 RunConfig 里
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from google.adk.agents import LlmAgent
from google.adk.agents.live_request_queue import LiveRequestQueue
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.runners import InMemoryRunner
from google.genai import types

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.bridge import (bridge_from_env, resolve_live_model,  # noqa: E402
                           thinking_catalog)
from server.keys import status_fields  # noqa: E402

APP_NAME = "gemini_live_3_8"
MODEL = os.environ.get("LIVE_MODEL", "gemini-3.8-live")   # ADK 用不带 models/ 前缀的 id
VOICE = os.environ.get("LIVE_VOICE", "Aoede")             # 固定单一音色
LANGUAGE = os.environ.get("LIVE_LANGUAGE", "cmn-CN")      # 固定输出语言（防漂移）
# 想把网页日志同时打到终端（排查用）：RELAY_TERMINAL_LOG=1
TERMINAL_LOG = os.environ.get("RELAY_TERMINAL_LOG", "0") == "1"
BRIDGE = bridge_from_env()

# ---------------- ADK thinking 档位补丁（ET 必需）----------------
# 背景（实测 ADK 2.9.2）：
#   1) RunConfig 没有 thinking_level 字段；
#   2) live flow 会在 before_model_callback 之后重建 live_connect_config，回调里写会被覆盖；
#   3) Gemini.connect 是真正建连前最后一站（它自己就在那里设 speech_config）——唯一可靠注入点。
# 代价：档位是模块级变量（单会话演示够用；多会话并行不同档位会互相影响）。
_ADK_THINKING_LEVEL: Optional[str] = None


def set_adk_thinking(level: Optional[str]) -> None:
    global _ADK_THINKING_LEVEL
    _ADK_THINKING_LEVEL = level or None


def install_adk_thinking_patch() -> bool:
    try:
        from google.adk.models.google_llm import Gemini
    except Exception as exc:  # noqa: BLE001
        print(f"[adk] 无法导入 Gemini，thinking 补丁跳过: {exc}")
        return False
    if getattr(Gemini, "_relay_thinking_patched", False):
        return True
    orig_connect = Gemini.connect

    @contextlib.asynccontextmanager
    async def connect(self, llm_request):  # noqa: ANN001
        lvl = _ADK_THINKING_LEVEL
        if lvl:
            try:
                lc = getattr(llm_request, "live_connect_config", None)
                if lc is not None:
                    lc.thinking_config = types.ThinkingConfig(thinking_level=lvl)
            except Exception:  # noqa: BLE001
                pass
        async with orig_connect(self, llm_request) as conn:
            yield conn

    Gemini.connect = connect
    Gemini._relay_thinking_patched = True   # type: ignore[attr-defined]
    print("[adk] thinking 档位补丁已安装（注入点：Gemini.connect）")
    return True


install_adk_thinking_patch()

app = FastAPI(title="gemini_live_3.8 relay (ADK)")


# ---------------- ADK 工具：普通 Python 函数即可 ----------------
def screenshot(source: str = "display") -> dict:
    """截取当前屏幕或窗口的画面，用于查看真实的界面与运行结果。

    Args:
        source: 截取来源，display / window / app 之一，默认 display。

    Returns:
        含 ok 与 path 的字典；path 是图片文件路径。
    """
    r = BRIDGE.screenshot(source)
    BRIDGE.emit_tool("screenshot", {"source": source}, r)
    return r


def read_code(path: str, focus: str = "", max_lines: int = 200) -> dict:
    """读取并理解项目里的代码/文本文件（不只看画面，还能看实现）。

    Args:
        path: 相对项目根目录的文件或目录路径。
        focus: 可选，要找的关键词/函数名，只返回匹配片段。
        max_lines: 可选，最多返回行数，默认 200。

    Returns:
        含 ok 与 content/summary 的字典。
    """
    r = BRIDGE.read_code(path, focus, max_lines)
    BRIDGE.emit_tool("read_code", {"path": path, "focus": focus}, r)
    return r


def write_file(path: str, content: str, mode: str = "create",
               overwrite: bool = False) -> dict:
    """在项目目录里新建/追加/覆盖一个文本文件。

    Args:
        path: 相对项目根目录的文件路径。
        content: 要写入的完整文本内容。
        mode: create（默认）或 append（追加）。
        overwrite: 已存在时是否允许覆盖（默认 False，覆盖前自动备份）。

    Returns:
        含 ok 与 summary 的字典。
    """
    r = BRIDGE.write_file(path, content, mode, overwrite)
    BRIDGE.emit_tool("write_file", {"path": path, "mode": mode}, r)
    return r


def run_agent(prompt: str, cwd: str = "", confirm: bool = False) -> dict:
    """把修改需求下发给 pi agent 执行，立刻返回任务号，任务在后台跑。

    【前置条件（硬约束）】必须先和用户讨论方案、列出优劣，得到用户明确同意后再调用；
    用户没确认前不要调用，也不要传 confirm=True。
    【prompt 要求】pi 看不到屏幕，也看不到你和用户的对话，所以 prompt 必须自洽，写全五要素：
    目标 / 现状与问题（具体界面位置与具体现象）/ 具体要求（尺寸·间距·颜色·文案·交互，能定量就定量）
    / 验收标准（改完应该看到什么）/ 约束（不许动什么）。

    Args:
        prompt: 自洽的完整指令，覆盖上面五要素；不要写「优化一下」这类模糊说法。
        cwd: 工作目录，可省略。
        confirm: 用户是否已明确同意下发。未确认时必须为 False（False 时不会真的下发，只返回待确认预览）。

    Returns:
        含 ok 与 job_id 的字典；未确认时返回 needs_confirmation 与 prompt_preview。
    """
    return BRIDGE.run_agent(prompt, cwd or None, confirm=confirm)


def read_status(job_id: str = "") -> dict:
    """查询 pi agent 的运行状态：是否在跑、当前阶段、产物、是否出错。

    Args:
        job_id: 任务号；省略则返回总体状态。

    Returns:
        状态字典。
    """
    return BRIDGE.read_status(job_id or None)


def pi_answer(request_id: str, choice: str = "", text: str = "",
              approved: Optional[bool] = None, passphrase: str = "",
              cancel: bool = False) -> dict:
    """把用户在语音里对 pi 的决策回答回填给 pi（不回它就会卡住）。

    Args:
        request_id: 决策 id（pi 的请求通知里给出）。
        choice: select 类：用户选中的选项原文。
        text: input/editor 类：用户口述的内容。
        approved: confirm 类：放行=True / 拒绝=False。
        passphrase: confirm 类必填：用户口头说出的口令原文（服务端会校验，不符直接拒绝）。
        cancel: True 表示取消该决策。

    Returns:
        含 ok 与 resolved 的字典；口令不符时 ok=False 且 rejected=True。
    """
    return BRIDGE.answer_pi(request_id, choice=choice or None, text=text or None,
                            approved=approved, passphrase=passphrase or None,
                            cancel=cancel)


TOOL_FUNCS = {"screenshot": screenshot, "read_code": read_code, "write_file": write_file,
              "run_agent": run_agent, "read_status": read_status, "pi_answer": pi_answer}


def persona_cfg(pid: str) -> Dict[str, Any]:
    data = json.loads((ROOT / "personas.json").read_text(encoding="utf-8"))
    return data["personas"].get(pid) or data["personas"][data["default"]]


def _thinking_callback(level: Optional[str]):
    """ADK 的 RunConfig 没有 thinking_level 字段（实测 2.9.2），
    但 LlmRequest.live_connect_config 里有 thinking_config。
    所以用官方的 before_model_callback 在发请求前注入，而不是改 ADK 源码。
    """
    if not level:
        return None

    def _cb(callback_context, llm_request):  # noqa: ANN001, ARG001
        try:
            lc = getattr(llm_request, "live_connect_config", None)
            if lc is not None:
                lc.thinking_config = types.ThinkingConfig(thinking_level=level)
        except Exception:  # noqa: BLE001
            pass
        return None

    return _cb


def build_agent(pid: str, model: str = MODEL,
                thinking: Optional[str] = None) -> LlmAgent:
    cfg = persona_cfg(pid)
    tools = [TOOL_FUNCS[t] for t in cfg.get("tools", []) if t in TOOL_FUNCS]
    kw: Dict[str, Any] = {"name": pid, "model": model,
                         "instruction": cfg["systemInstruction"], "tools": tools}
    cb = _thinking_callback(thinking)
    if cb is not None:
        kw["before_model_callback"] = cb
    return LlmAgent(**kw)


# ---------------- 路由（与裸 WS 版一致） ----------------
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
    # key_present 必须在这里出现：前端用它决定要不要显示「未找到 GEMINI_API_KEY」告警。
    # 注意 ADK 的 Key 由 google-genai SDK 从**进程环境变量**读取，不读 .env 文件。
    return {"impl": "adk", "model": MODEL, "voice": VOICE, "language": LANGUAGE,
            "thinking": thinking_catalog(),
            "proxy": os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"),
            **status_fields(),
            "bridge": BRIDGE.detect()}


@app.get("/healthz")
async def healthz():
    return JSONResponse({"ok": True})


# ---------------- 会话 ----------------
def live_run_config(thinking: Optional[str] = None) -> RunConfig:
    kw: Dict[str, Any] = {"streaming_mode": StreamingMode.BIDI,
                          "response_modalities": ["AUDIO"]}
    # 注意：thinking 档位不经 RunConfig 传（ADK 2.9.2 没这个字段），
    # 而是由 _thinking_callback 在每次模型请求前写入 live_connect_config.thinking_config。
    if hasattr(types, "AudioTranscriptionConfig"):
        kw["output_audio_transcription"] = types.AudioTranscriptionConfig()
        kw["input_audio_transcription"] = types.AudioTranscriptionConfig()
    try:  # 固定单一音色 + 输出语言
        sc_kw: Dict[str, Any] = {"voice_config": types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=VOICE))}
        if "language_code" in (getattr(types.SpeechConfig, "model_fields", None) or {}):
            sc_kw["language_code"] = LANGUAGE
        kw["speech_config"] = types.SpeechConfig(**sc_kw)
    except Exception:
        pass
    try:  # 长会话必需
        kw["context_window_compression"] = types.ContextWindowCompressionConfig(
            sliding_window=types.SlidingWindow())
    except Exception:
        pass
    return RunConfig(**kw)


@app.websocket("/ws/client")
async def ws_client(ws: WebSocket):
    await ws.accept()
    queue: Optional[LiveRequestQueue] = None
    task: Optional[asyncio.Task] = None
    runner: Optional[InMemoryRunner] = None

    async def send(obj: Dict[str, Any]) -> None:
        if TERMINAL_LOG and obj.get("type") == "log":
            print(f"[{obj.get('kind') or 'sys'}] {obj.get('message')}", flush=True)
        await ws.send_text(json.dumps(obj, ensure_ascii=False))

    try:
        while True:
            msg = json.loads(await ws.receive_text())
            kind = msg.get("type")

            if kind == "start":
                pid = msg.get("persona", "coding_buddy")
                loop = asyncio.get_running_loop()

                def pi_log(text: str) -> None:   # pi 事件可能来自其他线程
                    asyncio.run_coroutine_threadsafe(
                        send({"type": "log", "message": text}), loop)

                async def on_pi_dialog(dmsg: Dict[str, Any], dpid: str,
                                       timeout: Optional[float],
                                       meta: Optional[Dict[str, Any]] = None) -> None:
                    if not dpid or dmsg.get("type") == "extension_ui_response":
                        if dpid:
                            await send({"type": "pi_dialog_done", "id": dpid})
                        return
                    meta = meta or {}
                    idx, tot = meta.get("index"), meta.get("total")
                    opts = dmsg.get("options") or []
                    is_confirm = dmsg.get("method") == "confirm"
                    await send({"type": "pi_dialog", "id": dpid,
                                "method": dmsg.get("method"), "title": dmsg.get("title"),
                                "message": dmsg.get("message"), "options": opts,
                                "deadlineIn": timeout, "needsPassphrase": is_confirm,
                                "index": idx, "total": tot})
                    q = (f"【pi 需要你拍板 · 第 {idx} 个 / 共 {tot} 个】request_id={dpid}；"
                         f"类型={dmsg.get('method')}；标题={dmsg.get('title') or '-'}；"
                         f"说明={dmsg.get('message') or '-'}；"
                         + (f"可选项={'、'.join(map(str, opts))}；" if opts else "")
                         + "请只处理这一个问题：先念清本问题和选项"
                           f"（若共多个，先说「总共有 {tot} 个问题需要确认，这是第 {idx} 个」），"
                           "然后停下等用户回答；不要一次念完所有问题。"
                           "回答后调用 pi_answer 回填。"
                         + ("放行类请求：必须先完整念出操作，并要求用户说出完整口令。"
                            if is_confirm else ""))
                    queue.send_content(types.Content(parts=[types.Part(text=q)]))

                async def on_pi_progress(text: str) -> None:
                    q = (f"【任务进度更新 · 需要主动插话播报】{text}\n"
                         "请立刻用语音播报，开头用「抱歉打断您的对话，刚刚任务进度有更新」这类措辞，"
                         "再用一句话说清更新内容；若用户刚才在聊别的话题，播报完把话头递回去。")
                    await send({"type": "log", "message": f"进度播报：{text[:80]}"})
                    queue.send_content(types.Content(parts=[types.Part(text=q)]))

                def pi_dialog(dmsg: Dict[str, Any], dpid: str,
                              timeout: Optional[float],
                              meta: Optional[Dict[str, Any]] = None) -> None:
                    asyncio.run_coroutine_threadsafe(on_pi_dialog(dmsg, dpid, timeout, meta), loop)

                def pi_progress(text: str) -> None:
                    asyncio.run_coroutine_threadsafe(on_pi_progress(text), loop)

                BRIDGE.set_logger(pi_log)
                BRIDGE.set_dialog_handler(pi_dialog)
                BRIDGE.set_progress_handler(pi_progress)
                lv = resolve_live_model(msg.get("thinking"))
                if not lv.get("ok"):
                    await send({"type": "error", "message": lv["error"]})
                    continue
                set_adk_thinking(lv["thinking"])   # ET 必需：把档位交给 connect 补丁
                runner = InMemoryRunner(agent=build_agent(pid, lv["model"], lv["thinking"]),
                                        app_name=APP_NAME)
                session = await runner.session_service.create_session(
                    app_name=APP_NAME, user_id="browser")
                queue = LiveRequestQueue()
                await send({"type": "log",
                            "message": f"ADK 就绪（{lv['model']} · {lv['label']} · voice={VOICE} · persona={pid}）"})
                await send({"type": "ready", "persona": pid, "model": lv["model"],
                            "thinking": lv["thinking"], "variant": lv["variant"]})

                async def pump():
                    try:
                        async for event in runner.run_live(
                                user_id="browser", session_id=session.id,
                                live_request_queue=queue, run_config=live_run_config(lv["thinking"])):
                            parts_payload = []
                            content = getattr(event, "content", None)
                            for p in (getattr(content, "parts", None) or []) if content else []:
                                d = getattr(p, "inline_data", None)
                                if d is not None and getattr(d, "data", None):
                                    parts_payload.append(
                                        {"inlineData": {"mimeType": d.mime_type,
                                                        "data": base64.b64encode(d.data).decode()}})
                            ot = getattr(event, "output_transcription", None)
                            it = getattr(event, "input_transcription", None)
                            if it is not None and getattr(it, "text", ""):
                                BRIDGE.note_user_speech(it.text)   # confirm 口令第二道锁
                            if parts_payload or ot or it:
                                await send({"type": "upstream", "payload": {"serverContent": {
                                    "modelTurn": {"parts": parts_payload},
                                    "outputTranscription": {"text": getattr(ot, "text", "") or ""},
                                    "inputTranscription": {"text": getattr(it, "text", "") or ""},
                                    "turnComplete": bool(getattr(event, "turn_complete", False)),
                                }}})
                    except Exception as exc:  # noqa: BLE001
                        await send({"type": "error", "message": f"ADK 流中断: {exc}"})

                task = asyncio.create_task(pump())
                continue

            if queue is None:
                continue

            if kind == "audio":
                queue.send_realtime(types.Blob(
                    data=base64.b64decode(msg["data"]), mime_type="audio/pcm;rate=16000"))
            elif kind == "image":
                BRIDGE.note_frame(msg.get("data", ""), msg.get("mime", "image/jpeg"))
                try:
                    queue.send_realtime(types.Blob(
                        data=base64.b64decode(msg["data"]),
                        mime_type=msg.get("mime", "image/jpeg")))
                except Exception as exc:  # noqa: BLE001
                    await send({"type": "log",
                                "message": f"丢弃一帧（{type(exc).__name__}）"})
            elif kind == "text":
                queue.send_content(types.Content(parts=[types.Part(text=msg["text"])]))
            elif kind == "stop":
                queue.close()
                await send({"type": "closed"})
                break
    except WebSocketDisconnect:
        pass
    finally:
        try:
            queue and queue.close()
        except Exception:
            pass
        if task:
            task.cancel()
