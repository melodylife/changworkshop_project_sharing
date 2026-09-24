"""bridge.py — pi agent 适配层 + 工具声明

设计要点（对应决策 #3）：
  上层（Gemini Live / Qwen 的 function calling）只见四个动作：
      status / screenshot / run_agent / read_status
  真实后端可选：
      mode="stub" → 假任务，用于打通链路
      mode="rpc"  → 常驻 `pi --mode rpc` 进程（JSONL over stdin/stdout），真实执行

RPC 协议要点（已实测，docs/rpc.md）：
  - 命令：stdin 每行一个 JSON，带 id；响应 {"type":"response","id":...,"success":...,"data":...}
  - 事件：stdout 每行一个 JSON，无 id（bash_execution_update 除外）
  - 分帧：**只按 \\n 切**（JSON 字符串里可能有 U+2028/U+2029，不能用通用行读取器）
  - 完成信号：agent_settled（agent_end 之后仍可能有 retry/compaction，不能当完成）
  - 结果回读：get_last_assistant_text / get_session_stats / get_state
  - 对话框类 extension_ui_request（select/confirm/input/editor）会**阻塞等应答**，
    headless 下安全默认 = 回 cancelled:true（= 不批准危险操作），并上报日志
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

# 暴露给上游模型的函数声明
FUNCTION_DECLARATIONS: List[Dict[str, Any]] = [
    {
        "name": "screenshot",
        "description": "截取当前屏幕或指定窗口的画面，用于查看真实的界面/运行结果。",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "source": {"type": "STRING", "description": "display | window | app，默认 display"}
            },
        },
    },
    {
        "name": "run_agent",
        "description": (
            "把修改需求下发给 pi agent 执行（后台跑，立刻返回任务号）。"
            "【前置条件（硬约束）】必须先和用户讨论方案、列出优劣，并得到用户明确同意；"
            "用户没确认之前禁止调用，也禁止传 confirm=true。"
            "【prompt 要求】pi 看不到屏幕，也看不到你和用户的对话，prompt 必须自洽，写全五要素："
            "目标 / 现状与问题（具体界面位置与具体现象）/ 具体要求（尺寸·间距·颜色·文案·交互，能定量就定量）"
            " / 验收标准（改完应看到什么）/ 约束（不许动什么）。禁止「优化一下」这类模糊指令。"
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "prompt": {"type": "STRING",
                           "description": "自洽的完整指令，覆盖五要素（见工具描述），不看屏幕也能准确理解"},
                "cwd": {"type": "STRING", "description": "工作目录，可省略"},
                "confirm": {"type": "BOOLEAN",
                            "description": "用户是否已明确同意下发；未确认时必须为 false（false 不会真的下发，只回待确认预览）"},
            },
            "required": ["prompt", "confirm"],
        },
    },
    {
        "name": "pi_answer",
        "description": (
            "把用户在语音里对 pi 的决策回答回填给 pi（pi 正等着这个回答，不回它就会卡住）。"
            "【什么时候用】收到 pi 的决策请求通知时（日志/页面会显示 request_id 与截止时间），"
            "用语音向用户转述问题，等用户回答后再调用本工具。"
            "【confirm 类·危险操作】必须要求用户口头说出完整口令，并原样填入 passphrase；"
            "口令不对会被服务端直接拒绝（未放行）。念问题时要先把 pi 的原始命令/操作完整念一遍。"
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "request_id": {"type": "STRING", "description": "决策 id（pi 的请求通知里给出）"},
                "choice": {"type": "STRING", "description": "select 类：用户选中的选项原文"},
                "text": {"type": "STRING", "description": "input/editor 类：用户口述的内容"},
                "approved": {"type": "BOOLEAN", "description": "confirm 类：放行=true / 拒绝=false"},
                "passphrase": {"type": "STRING",
                               "description": "confirm 类必填：用户口头说出的口令原文（服务端会校验）"},
            },
            "required": ["request_id"],
        },
    },
    {
        "name": "read_code",
        "description": (
            "读取并理解项目里的代码/文本文件（眼睛之外再给搭子一双手）。"
            "path 相对项目根目录；给 focus 时只回匹配片段（省上下文）；"
            "path 指向目录时返回文件清单；文件很大且未给 focus 时返回结构大纲。"
            "【什么时候用】需要判断代码逻辑/实现细节（而不只是看画面）时，先用它读源码再下结论。"
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "path": {"type": "STRING", "description": "相对项目根目录的文件或目录路径"},
                "focus": {"type": "STRING", "description": "可选：要找的关键词/函数名，只返回匹配片段"},
                "max_lines": {"type": "NUMBER", "description": "可选：最多返回行数，默认 200"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": (
            "在项目目录里新建/追加/覆盖一个文本文件（搭子自己动手写文件，不必绕 pi）。"
            "默认只新建：目标已存在时会拒绝，除非显式 overwrite=true（覆盖前自动备份原文件）。"
            "只能写 PI_CWD 以内的路径。写完请用 read_code 或截图复核结果。"
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "path": {"type": "STRING", "description": "相对项目根目录的文件路径"},
                "content": {"type": "STRING", "description": "要写入的完整文本内容"},
                "mode": {"type": "STRING", "description": "create（默认）| append（追加）"},
                "overwrite": {"type": "BOOLEAN", "description": "已存在时是否允许覆盖（默认 false）"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "read_status",
        "description": "查询 pi agent 的运行状态：是否在跑、当前阶段、产物文件、token/成本、最后一次输出。",
        "parameters": {"type": "OBJECT", "properties": {"job_id": {"type": "STRING"}}},
    },
]

# pi CLI 可能不在 PATH（npm/nvm 安装），这里显式兜底几个位置
PI_CLI_CANDIDATES = (
    os.path.expanduser("~/.nvm/versions/node/v24.18.1/bin/pi"),
    os.path.expanduser("~/.local/bin/pi"),
    os.path.expanduser("/usr/local/bin/pi"),
    "/opt/homebrew/bin/pi",
)


def resolve_pi_cli(explicit: Optional[str] = None) -> Optional[str]:
    for c in ((explicit,) if explicit else PI_CLI_CANDIDATES):
        hit = shutil.which(c)
        if hit:
            return hit
    return None


# ---- Live 模型档位：普通款 / Extended Thinking ----
LIVE_BASE_MODEL = "gemini-3.8-live"
LIVE_ET_MODEL = "gemini-3.8-live-extended-thinking"
THINKING_LEVELS = ("low", "medium", "high")      # 实测合法值（off 不存在，传了报 Invalid value）


def thinking_catalog() -> Dict[str, Any]:
    """给 /api/status 与前端用的档位目录（实测结论写在这里）"""
    return {
        "supported": True,
        "levels": list(THINKING_LEVELS),
        "off_label": "关闭（普通款）",
        "base_model": os.environ.get("LIVE_BASE_MODEL") or LIVE_BASE_MODEL,
        "et_model": os.environ.get("LIVE_ET_MODEL") or LIVE_ET_MODEL,
        "notes": "关闭=普通款 gemini-3.8-live（无思考档，传 thinkingLevel 会被 1007 拒）；"
                 "low/medium/high=ET（必须显式指定）",
    }


def resolve_live_model(thinking: Optional[str] = None) -> Dict[str, Any]:
    """把「推理档位」解析成模型 + thinkingConfig。

    关闭/不传 → 普通款（不发 thinkingConfig）
    low/medium/high → ET + generationConfig.thinkingConfig.thinkingLevel
    环境变量 LIVE_MODEL 若显式设置则优先（旧行为兼容）；LIVE_THINKING 作为默认档位。
    """
    base = (os.environ.get("LIVE_BASE_MODEL") or LIVE_BASE_MODEL).strip()
    et = (os.environ.get("LIVE_ET_MODEL") or LIVE_ET_MODEL).strip()
    forced = (os.environ.get("LIVE_MODEL") or "").strip()
    lvl = (thinking if thinking is not None else os.environ.get("LIVE_THINKING") or "")
    lvl = str(lvl).strip().lower()
    if lvl in ("", "off", "none", "base", "0", "false"):
        return {"ok": True, "variant": "base", "thinking": None, "model": forced or base,
                "thinkingConfig": None, "label": "普通款"}
    if lvl not in THINKING_LEVELS:
        return {"ok": False, "variant": "invalid", "thinking": lvl, "levels": list(THINKING_LEVELS),
                "error": f"非法推理档位 {lvl!r}；合法值：关闭 / " + " / ".join(THINKING_LEVELS)}
    return {"ok": True, "variant": "extended", "thinking": lvl, "model": forced or et,
            "thinkingConfig": {"thinkingLevel": lvl}, "label": f"Extended Thinking（{lvl}）"}


def normalize_live_model(model: str) -> str:
    """裸 WS 版需要 models/ 前缀，ADK 版不要；这里统一供给裸版用。"""
    m = (model or "").strip()
    return m if m.startswith("models/") else "models/" + m


def tool_summary(name: str, result: Dict[str, Any]) -> str:
    """给前端日志用的一句话工具结果摘要（演示要看的就是这行）。"""
    r = result or {}
    if not r.get("ok"):
        if r.get("needs_confirmation"):
            return "未下发（等用户确认）"
        return "失败：" + str(r.get("error") or "")[:60]
    if name == "screenshot":
        return "截图 OK（桩图：还没浏览器帧）" if r.get("stub") else f"截图 OK（{r.get('source') or ''}）"
    if name == "read_code":
        return str(r.get("summary") or f"读取 {r.get('path') or ''}")[:80]
    if name == "write_file":
        return str(r.get("summary") or f"写入 {r.get('path') or ''}")[:80]
    if name == "run_agent":
        return f"已下发 pi（{r.get('job_id') or ''}）"
    if name == "read_status":
        pi = r.get("pi") or {}
        if pi:
            tok = (pi.get("tokens") or {}).get("total")
            return ("pi 运行中" if pi.get("isStreaming") else "pi 空闲") + (f" · tokens={tok}" if tok else "")
        return "pi 状态已回读"
    if name == "pi_answer":
        return "已回填" + str(r.get("resolved") or r.get("error") or "")
    return "OK"


# ---- pi 决策对话框（extension_ui_request）策略 ----
DIALOG_METHODS = {"select", "confirm", "input", "editor"}      # 会阻塞等应答
NOTIFY_METHODS = {"notify", "setStatus", "setWidget", "setTitle",
                  "set_editor_text"}                            # 即发即忘，可忽略

# 危险操作（confirm 类）的口头口令：服务端校验，不依赖模型自觉
# 危险操作（confirm 类）的口头口令：服务端校验，不依赖模型自觉
# 通用短语容易被自然对话误触发 → 默认再叠一道「语音转写核对」（confirm_mode=transcript）
DEFAULT_PASSPHRASE = "确认执行"
_PUNCT = r"[\s，。,.!！?？、~·\"'“”‘’()（）:：;；\-—]"


def normalize_phrase(s: str) -> str:
    """去空格与标点 + 转小写，用于口令比对（容忍"确认执行 松果。"这种）。"""
    return re.sub(_PUNCT, "", (s or "").lower())


def passphrase_ok(said: str, expect: str) -> bool:
    a, b = normalize_phrase(said), normalize_phrase(expect)
    return bool(b) and (a == b or b in a)


class PiRpcClient:
    """常驻 pi --mode rpc 客户端：严格 LF 分帧，线程安全。"""

    DIALOG_METHODS = {"select", "confirm", "input", "editor"}

    def __init__(self, cli: str, cwd: Optional[str] = None, model: Optional[str] = None,
                 thinking: Optional[str] = None, extra_args: Optional[List[str]] = None,
                 on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
                 on_dialog: Optional[Callable[[Dict[str, Any], str, Optional[float]], None]] = None,
                 on_log: Optional[Callable[[str], None]] = None,
                 dialog_mode: str = "ask-user", dialog_timeout: float = 60.0,
                 passphrase: str = DEFAULT_PASSPHRASE,
                 confirm_mode: str = "transcript",
                 speech_probe: Optional[Callable[[float], str]] = None,
                 name: str = "relay"):
        self.cli = cli
        self.cwd = cwd or os.getcwd()
        self.model = model
        self.thinking = thinking
        self.extra_args = list(extra_args or [])
        self.on_event = on_event
        self.on_dialog = on_dialog
        self.on_log = on_log
        self.dialog_mode = dialog_mode          # ask-user（转语音）| auto-cancel
        self.dialog_timeout = float(dialog_timeout)
        self.passphrase = passphrase
        # transcript：口令必须同时出现在真实语音转写里（推荐）；model：只信模型回填
        self.confirm_mode = confirm_mode
        self.speech_probe = speech_probe          # (since_ts) -> 该时间之后的转写文本
        self._dialog_opened: Dict[str, float] = {}
        self.name = name
        self.proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._cv = threading.Condition()
        self._resp: Dict[str, Dict[str, Any]] = {}
        self.stderr_tail: deque = deque(maxlen=20)
        # 挂起中的对话框：id -> 记录；等待用 Event，避免阻塞 reader 线程
        self.pending: Dict[str, Dict[str, Any]] = {}
        self._pending_lock = threading.Lock()
        self._pending_ev: Dict[str, threading.Event] = {}
        self.current_dialog: Optional[str] = None   # 正在等用户回答的那一个（串行化）
        self._batch_resolved = 0                    # 本批已答完几个（用于 "第 k/共 N 个"）
        self.announce_pending = False               # 已排定一次"稍后抛出"
        # pi 通常是"一束"抛出多个问题；先等一小下再开口，总数才准
        self.dialog_batch_wait = float(os.environ.get("PI_DIALOG_BATCH_WAIT", "0.8"))

    # ---------- 生命周期 ----------
    def cmd(self) -> List[str]:
        out = [self.cli, "--mode", "rpc", "--name", self.name]
        if self.model:
            out += ["--model", self.model]
        if self.thinking:
            out += ["--thinking", self.thinking]
        return out + self.extra_args

    @property
    def alive(self) -> bool:
        return bool(self.proc and self.proc.poll() is None)

    def start(self) -> None:
        with self._lock:
            if self.alive:
                return
            env = dict(os.environ)
            env["PATH"] = os.path.dirname(self.cli) + os.pathsep + env.get("PATH", "")
            self.proc = subprocess.Popen(
                self.cmd(), cwd=self.cwd, env=env, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1,
            )
            self._resp.clear()
            threading.Thread(target=self._read_loop, daemon=True).start()
            threading.Thread(target=self._stderr_loop, daemon=True).start()
            self._safe_log(f"pi rpc 已启动（{os.path.basename(self.cli)} · "
                           f"model={self.model or 'default'} · cwd={self.cwd}）")

    def stop(self) -> None:
        p, self.proc = self.proc, None
        if not p:
            return
        try:
            if p.stdin:
                p.stdin.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            p.terminate()
            p.wait(timeout=8)
        except Exception:  # noqa: BLE001
            try:
                p.kill()
            except Exception:  # noqa: BLE001
                pass

    # ---------- 内部线程 ----------
    def _read_loop(self) -> None:
        try:
            for line in self.proc.stdout:  # type: ignore[union-attr]
                line = line.rstrip("\r\n")     # 只按 \n 分帧，顺带容忍 \r\n
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                kind = msg.get("type")
                if kind == "response":
                    with self._cv:
                        self._resp[msg.get("id")] = msg
                        self._cv.notify_all()
                    continue
                if kind == "extension_ui_request":
                    self._handle_ui_request(msg)
                    continue
                if self.on_event:
                    try:
                        self.on_event(msg)
                    except Exception:  # noqa: BLE001
                        pass
        except Exception:  # noqa: BLE001
            pass

    def _stderr_loop(self) -> None:
        try:
            for line in self.proc.stderr:  # type: ignore[union-attr]
                line = line.strip()
                if line:
                    self.stderr_tail.append(line)
        except Exception:  # noqa: BLE001
            pass

    def _handle_ui_request(self, msg: Dict[str, Any]) -> None:
        method = msg.get("method")
        title = (msg.get("title") or "").strip()

        # 甲类：即发即忘，不阻塞；上报日志 + 通知前端
        if method not in DIALOG_METHODS:
            if self.on_dialog:
                try:
                    self.on_dialog(msg, "", None)
                except Exception:  # noqa: BLE001
                    pass
            if method in ("notify", "setTitle"):
                self._safe_log(f"pi 通知 [{method}] {title or msg.get('message') or ''}")
            return

        pid = str(msg.get("id") or uuid.uuid4().hex[:8])
        given = msg.get("timeout")
        timeout = (float(given) / 1000.0) if isinstance(given, (int, float)) else self.dialog_timeout

        # 策略：auto-cancel（无人值守安全默认） / ask-user（转语音等人工确认）
        if self.dialog_mode != "ask-user":
            self._respond_dialog(pid, {"cancelled": True})
            self._safe_log(f"pi 请求决策 [{method}] {title} → 已自动取消（auto-cancel 模式）")
            return

        with self._pending_lock:
            self.pending[pid] = {
                "id": pid, "method": method, "title": title,
                "message": msg.get("message") or "", "options": msg.get("options") or [],
                "placeholder": msg.get("placeholder") or "",
                "deadline": time.time() + timeout, "attempts": 0,
            }
            self._pending_ev[pid] = threading.Event()
            self._dialog_opened[pid] = time.time()

        opts = "、".join(str(o) for o in (msg.get("options") or []))
        self._safe_log(f"pi 提问已入队 [{method}] {title}"
                       + (f"（选项：{opts}）" if opts else "")
                       + f" · {int(timeout)}s 内不答就自动取消")
        # 串行化：一次只向前端/模型抛一个问题，答完再抛下一个
        self._schedule_announce()

    def _schedule_announce(self) -> None:
        """稍等 dialog_batch_wait 再抛：让 pi 同时抛出的多个问题先入队，总数才准确。"""
        if self.current_dialog or self.announce_pending:
            return
        if self.dialog_batch_wait <= 0:
            self._announce_next()
            return
        self.announce_pending = True
        timer = threading.Timer(self.dialog_batch_wait, self._announce_after_wait)
        timer.daemon = True
        timer.start()

    def _announce_after_wait(self) -> None:
        self.announce_pending = False
        self._announce_next()

    def _announce_next(self) -> None:
        """把队列里第一个尚未提问的决策抛出去（同时只有一个在等回答）。"""
        if self.current_dialog:
            return
        with self._pending_lock:
            ids = list(self.pending.keys())
        if not ids:
            self._batch_resolved = 0
            return
        pid = ids[0]
        rec = dict(self.pending.get(pid) or {})
        self.current_dialog = pid
        total = len(ids) + self._batch_resolved
        index = self._batch_resolved + 1
        remain = max(0.0, float(rec.get("deadline", 0)) - time.time())
        opts = "、".join(str(o) for o in (rec.get("options") or []))
        self._safe_log(f"请用户拍板（第 {index}/{total} 个）[{rec.get('method')}] {rec.get('title')}"
                       + (f"（选项：{opts}）" if opts else "")
                       + f" · {int(remain)}s 内不答就自动取消")
        meta = {"index": index, "total": total, "remaining": remain,
                "pending": [i for i in ids]}
        if self.on_dialog:
            try:
                self.on_dialog({**rec, "type": "extension_ui_request"}, pid, remain, meta)
            except Exception:  # noqa: BLE001
                pass
        threading.Thread(target=self._await_dialog, args=(pid, remain), daemon=True).start()

    def _await_dialog(self, pid: str, timeout: float) -> None:
        ev = self._pending_ev.get(pid)
        if ev is None or ev.wait(timeout):
            return
        self._finish_dialog(pid, {"cancelled": True},
                            f"超时 {int(timeout)}s 未得到确认 → 已自动取消（未放行）")

    def _respond_dialog(self, pid: str, payload: Dict[str, Any]) -> bool:
        frame = {"type": "extension_ui_response", "id": pid, **payload}
        try:
            self.send(frame)
            return True
        except Exception:  # noqa: BLE001
            return False

    def _finish_dialog(self, pid: str, payload: Dict[str, Any], note: str) -> bool:
        with self._pending_lock:
            if pid not in self.pending:
                return False
            self.pending.pop(pid, None)
            ev = self._pending_ev.pop(pid, None)
        delivered = self._respond_dialog(pid, payload)
        if ev:
            ev.set()
        self._dialog_opened.pop(pid, None)
        if self.current_dialog == pid:
            self.current_dialog = None
            self._batch_resolved += 1
        self._safe_log(note + ("" if delivered else "（但未送达：pi 进程已退出）"))
        if self.on_dialog:
            try:
                self.on_dialog({"type": "extension_ui_response", "id": pid, **payload},
                               pid, 0.0, {"resolved": True})
            except Exception:  # noqa: BLE001
                pass
        # 答完一个 → 抛下一个（保证“逐个问、逐个答”）
        if delivered:
            self._announce_next()
        return delivered

    def pending_list(self) -> List[Dict[str, Any]]:
        with self._pending_lock:
            return [dict(v) for v in self.pending.values()]

    def answer_dialog(self, request_id: str, choice: Optional[str] = None,
                      text: Optional[str] = None, approved: Optional[bool] = None,
                      passphrase: Optional[str] = None,
                      cancel: bool = False) -> Dict[str, Any]:
        """由人工（经语音/UI）给出的决策，回填给 pi。confirm 类必须带正确口令。"""
        with self._pending_lock:
            rec = self.pending.get(request_id)
        if not rec:
            return {"ok": False,
                    "error": f"没有待回答的决策 {request_id}（可能已超时取消或已回答）",
                    "pending": [v["id"] for v in self.pending_list()]}
        if self.current_dialog and request_id != self.current_dialog:
            return {"ok": False, "wrong_question": True,
                    "error": (f"顺序不符：当前正在等用户回答的是 {self.current_dialog}，"
                              f"不是 {request_id}。请先把当前问题问完并回填。")}
        method = rec["method"]
        if cancel:
            self._finish_dialog(request_id, {"cancelled": True},
                                f"决策 {request_id} → 用户取消")
            return {"ok": True, "resolved": "cancelled"}
        if method == "confirm":
            if approved is None:
                return {"ok": False, "error": "confirm 类必须给 approved=true/false"}
            if not passphrase_ok(passphrase or "", self.passphrase):
                with self._pending_lock:
                    rec["attempts"] = rec.get("attempts", 0) + 1
                    attempts = rec["attempts"]
                if attempts >= 3:
                    ok = self._finish_dialog(request_id, {"cancelled": True},
                                             f"{request_id} 口令连续 3 次不符 → 已取消（未放行）")
                    return {"ok": False, "error": "口令不符，已达 3 次上限，已取消",
                            "cancelled": True, "delivered": ok}
                return {"ok": False, "rejected": True, "attempts": attempts,
                        "error": "口令不符：未放行（pi 仍在等，可让用户再说一次）"}
            # 第二道锁：口令必须真的出现在「这次提问之后」的语音转写里，
            # 避免模型把别处听来的“确认执行”当成本次授权。
            if self.confirm_mode == "transcript" and self.speech_probe:
                since = self._dialog_opened.get(request_id, 0.0)
                heard = self.speech_probe(since)
                if not passphrase_ok(heard, self.passphrase):
                    return {"ok": False, "rejected": True,
                            "error": ("未在语音转写里听到口令（本次提问之后）：未放行。"
                                      "请当面再完整说一次口令。")}
            delivered = self._finish_dialog(
                request_id, {"confirmed": bool(approved)},
                f"决策 {request_id} → 用户{'放行' if approved else '拒绝'}（口令校验通过）")
            if not delivered:
                return {"ok": False, "error": "口令已通过，但 pi 进程已退出，决策未送达"}
            return {"ok": True, "resolved": "confirm", "approved": bool(approved)}

        if method == "select":
            val = choice or text
            if not val:
                return {"ok": False, "error": "select 类必须给 choice（用户选的选项原文）"}
            delivered = self._finish_dialog(request_id, {"value": val},
                                            f"决策 {request_id} → 用户选择「{val}」")
            return {"ok": delivered, "resolved": "select", "value": val,
                    "error": None if delivered else "pi 进程已退出，决策未送达"}

        val = text or choice
        if val is None:
            return {"ok": False, "error": f"{method} 类必须给 text"}
        delivered = self._finish_dialog(request_id, {"value": val},
                                        f"决策 {request_id} → 用户回答：{str(val)[:80]}")
        return {"ok": delivered, "resolved": method, "value": val,
                "error": None if delivered else "pi 进程已退出，决策未送达"}

    def _safe_log(self, text: str) -> None:
        if self.on_log:
            try:
                self.on_log(text)
            except Exception:  # noqa: BLE001
                pass

    # ---------- 收发 ----------
    def send(self, obj: Dict[str, Any]) -> None:
        with self._lock:
            if not self.alive:
                raise RuntimeError("pi rpc 进程未运行")
            assert self.proc and self.proc.stdin
            self.proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()

    def request(self, obj: Dict[str, Any], timeout: float = 60.0) -> Dict[str, Any]:
        rid = obj.get("id") or ("req-" + uuid.uuid4().hex[:8])
        obj = {**obj, "id": rid}
        with self._cv:
            self._resp.pop(rid, None)
        self.send(obj)
        deadline = time.time() + timeout
        with self._cv:
            while rid not in self._resp:
                remain = deadline - time.time()
                if remain <= 0:
                    raise TimeoutError(f"pi rpc 无响应: {obj.get('type')}（{timeout}s）")
                self._cv.wait(remain)
            return self._resp.pop(rid)

    def prompt(self, text: str, images: Optional[List[Dict[str, Any]]] = None,
               timeout: float = 30.0) -> Dict[str, Any]:
        obj: Dict[str, Any] = {"type": "prompt", "message": text}
        if images:
            obj["images"] = images          # [{"type":"image","data":b64,"mimeType":"image/jpeg"}]
        return self.request(obj, timeout=timeout)


def bridge_from_env() -> PiBridge:
    """按环境变量构造桥接层（三个 server 共用，避免各写一份）。

    PI_BRIDGE_MODE  stub | rpc（默认 stub，rpc 才是真调 pi）
    PI_CLI          pi 可执行文件路径（默认自动探测）
    PI_MODEL        显式 pin 的模型，如 deepseek/deepseek-flash
    PI_THINKING     off | minimal | low | medium | high
    PI_CWD          pi 的工作目录（默认继承服务端 cwd）
    PI_RPC_ARGS     附加给 `pi --mode rpc` 的参数（空格分隔，如 --no-extensions）
    """
    raw_args = os.environ.get("PI_RPC_ARGS", "").strip()
    return PiBridge(
        mode=os.environ.get("PI_BRIDGE_MODE", "stub"),
        pi_cli=os.environ.get("PI_CLI"),
        pi_model=os.environ.get("PI_MODEL"),
        pi_thinking=os.environ.get("PI_THINKING"),
        pi_cwd=os.environ.get("PI_CWD"),
        pi_args=raw_args.split() if raw_args else None,
        code_root=os.environ.get("PI_CWD"),
        dialog_mode=os.environ.get("PI_DIALOG_MODE", "ask-user"),
        dialog_timeout=float(os.environ.get("PI_DIALOG_TIMEOUT", "60")),
        passphrase=os.environ.get("PI_CONFIRM_PHRASE", DEFAULT_PASSPHRASE),
        confirm_mode=os.environ.get("PI_CONFIRM_MODE", "transcript"),
    )


@dataclass
class Job:
    id: str
    prompt: str
    cwd: str
    status: str = "queued"          # queued | running | done | failed
    phase: str = "queued"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    artifacts: List[str] = field(default_factory=list)
    error: Optional[str] = None
    backend: str = "stub"           # stub | rpc
    pi_session: Optional[str] = None
    events: int = 0
    tools: List[str] = field(default_factory=list)
    last_text: Optional[str] = None
    tokens: Optional[Dict[str, Any]] = None
    cost: Optional[float] = None


class PiBridge:
    """pi agent 适配器。mode=stub（假任务） 或 mode=rpc（常驻 pi RPC 进程）。"""

    def __init__(self, mode: str = "stub", stub_image: Optional[str] = None,
                 pi_cli: Optional[str] = None, pi_model: Optional[str] = None,
                 pi_thinking: Optional[str] = None, pi_cwd: Optional[str] = None,
                 pi_args: Optional[List[str]] = None, dialog_mode: str = "ask-user",
                 dialog_timeout: float = 60.0, passphrase: str = DEFAULT_PASSPHRASE,
                 confirm_mode: str = "transcript", code_root: Optional[str] = None):
        self.mode = mode
        self.code_root = os.path.abspath(os.path.expanduser(
            code_root or os.environ.get("PI_CWD") or os.getcwd()))
        self.stub_image = stub_image or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "stub.png"
        )
        self.jobs: Dict[str, Job] = {}
        self.order: List[str] = []
        self.active: Optional[str] = None
        self._log: Optional[Callable[[str], None]] = None
        self._dialog_sink: Optional[Callable[[Dict[str, Any], str, Optional[float]], None]] = None
        self._progress_sink: Optional[Callable[[str], None]] = None
        self._tool_sink: Optional[Callable[[str, Dict[str, Any], Dict[str, Any]], None]] = None
        self.progress_events = set(
            os.environ.get("PI_PROGRESS_EVENTS", "settled").replace(" ", "").split(","))
        self._speech: deque = deque(maxlen=200)      # (ts, 用户语音转写) 滚动缓存
        self.last_frame: Optional[Dict[str, Any]] = None   # 浏览器最近一帧
        self.frame_max_age = float(os.environ.get("PI_FRAME_MAX_AGE", "20"))
        self._lock = threading.Lock()
        self.rpc: Optional[PiRpcClient] = None
        self.cli = resolve_pi_cli(pi_cli)
        if mode == "rpc":
            if not self.cli:
                self.mode = "stub"
                self.last_error = "未找到 pi CLI，已回退 stub"
            else:
                self.rpc = PiRpcClient(
                    self.cli, cwd=pi_cwd, model=pi_model, thinking=pi_thinking,
                    extra_args=pi_args, on_event=self._on_pi_event,
                    on_dialog=self._on_pi_dialog,
                    on_log=lambda m: self._emit(m), name="relay",
                    dialog_mode=dialog_mode, dialog_timeout=dialog_timeout,
                    passphrase=passphrase,
                    confirm_mode=confirm_mode,
                    speech_probe=self._speech_since,
                )

    # ---------- 用户语音转写缓存（confirm 类口令的第二道锁）----------
    def note_user_speech(self, text: str) -> None:
        if text and text.strip():
            self._speech.append((time.time(), text.strip()))

    def _speech_since(self, since_ts: float) -> str:
        return "".join(t for ts, t in list(self._speech) if ts >= (since_ts or 0))

    # ---------- 决策对话框：转给当前 Live 会话 ----------
    def set_dialog_handler(self, fn: Optional[Callable[[Dict[str, Any], str, Optional[float]], None]]) -> None:
        self._dialog_sink = fn

    # ---------- 进度播报（可打断正在进行的对话）----------
    def set_progress_handler(self, fn: Optional[Callable[[str], None]]) -> None:
        self._progress_sink = fn

    def _emit_progress(self, text: str) -> None:
        if self._progress_sink:
            try:
                self._progress_sink(text)
            except Exception:  # noqa: BLE001
                pass

    def _on_pi_dialog(self, msg: Dict[str, Any], pid: str, timeout: Optional[float]) -> None:
        if self._dialog_sink:
            try:
                self._dialog_sink(msg, pid, timeout)
            except Exception:  # noqa: BLE001
                pass

    def pending_dialogs(self) -> List[Dict[str, Any]]:
        return self.rpc.pending_list() if self.rpc else []

    def answer_pi(self, request_id: str, choice: Optional[str] = None,
                  text: Optional[str] = None, approved: Optional[bool] = None,
                  passphrase: Optional[str] = None, cancel: bool = False) -> Dict[str, Any]:
        if not self.rpc:
            return {"ok": False, "error": "pi 未接入（当前是 stub 模式）"}
        pending = self.rpc.pending_list()
        if not pending:
            return {"ok": False, "error": "当前没有待回答的决策（可能已超时取消或已回答）"}
        return self.rpc.answer_dialog(request_id, choice=choice, text=text,
                                      approved=approved, passphrase=passphrase, cancel=cancel)

    def alive_pi(self) -> bool:
        return bool(self.rpc and self.rpc.alive)

    # ---------- 日志出口（由各 server 注入，转发给浏览器）----------
    def set_logger(self, fn: Optional[Callable[[str], None]]) -> None:
        self._log = fn

    # ---------- 工具调用回显（演示日志用）----------
    def set_tool_logger(self, fn: Optional[Callable[[str, Dict[str, Any], Dict[str, Any]], None]]) -> None:
        self._tool_sink = fn

    def emit_tool(self, name: str, args: Dict[str, Any], result: Dict[str, Any]) -> None:
        if self._tool_sink:
            try:
                self._tool_sink(name, args or {}, result or {})
            except Exception:  # noqa: BLE001
                pass

    def _emit(self, text: str) -> None:
        if self._log:
            try:
                self._log(text)
            except Exception:  # noqa: BLE001
                pass

    # ---------- 后端探测 ----------
    def detect(self) -> Dict[str, Any]:
        home_pi = os.path.isdir(os.path.expanduser("~/.pi"))
        return {
            "mode": self.mode,
            "pi_cli": self.cli,
            "pi_home_exists": home_pi,
            "rpc_alive": bool(self.rpc and self.rpc.alive),
            "pi_model": self.rpc.model if self.rpc else None,
            "notes": ("RPC 常驻，事件流 + 图片直传" if self.mode == "rpc"
                      else "stub：未真正调用 pi"),
        }

    # ---------- 工具实现 ----------
    def note_frame(self, data_b64: str, mime: str = "image/jpeg") -> None:
        """缓存浏览器推上来的最新一帧（屏幕共享/摄像头）——供 screenshot 返回。"""
        if not data_b64:
            return
        with self._lock:
            self.last_frame = {"data": data_b64, "mime": mime or "image/jpeg",
                               "ts": time.time()}

    def _frame_path(self) -> Optional[str]:
        with self._lock:
            fr = dict(self.last_frame) if self.last_frame else None
        if not fr or (time.time() - fr["ts"]) > self.frame_max_age:
            return None
        ext = ".png" if "png" in str(fr["mime"]) else ".jpg"
        path = os.path.join(tempfile.gettempdir(), f"relay-last-frame{ext}")
        try:
            with open(path, "wb") as fh:
                fh.write(base64.b64decode(fr["data"]))
            return path
        except Exception:  # noqa: BLE001
            return None

    def screenshot(self, source: str = "display") -> Dict[str, Any]:
        """优先返回浏览器最近一帧（= 搭子/用户眼前真实画面）；没有才回退桩图。

        为什么这么做：浏览器每杧推一帧（共享屏幕/摄像头），这就是搭子"看到"的东西，
        也是用户正在看的画面。实时截屏需要屏幕录制权限，先用这条路零权限跑通。
        """
        path = self._frame_path()
        if path:
            with self._lock:
                age = int((time.time() - (self.last_frame or {}).get("ts", 0)) * 1000)
            return {"ok": True, "path": path, "stub": False,
                    "source": f"browser-frame({source})", "age_ms": age}
        if not os.path.exists(self.stub_image):
            return {"ok": False, "error": f"stub image missing: {self.stub_image}"}
        return {"ok": True, "path": self.stub_image, "source": source, "stub": True,
                "note": "无浏览器帧（未开屏幕共享/摄像头？），返回桩图"}

    # ---------- read_code：读取与理解代码 ----------
    def read_code(self, path: str = "", focus: str = "",
                  max_lines: int = 200) -> Dict[str, Any]:
        """读文件/目录，用于涉代码逻辑时先看实现。

        安全：只允许读 code_root（默认 pi 的工作目录）以内的路径，防目录穿越。
        省上下文：给 focus 只回匹配片段；文件大且未给 focus 时回结构大纲。
        """
        from pathlib import Path

        root = Path(self.code_root).expanduser().resolve()
        if not path:
            return {"ok": False, "error": "需要 path（相对项目根目录）", "root": str(root)}
        raw = Path(path).expanduser()
        target = (raw if raw.is_absolute() else (root / raw)).resolve()
        if not str(target).startswith(str(root)):
            return {"ok": False, "error": f"拒绝：{path} 不在允许目录内", "root": str(root),
                    "hint": f"只能读 {root} 以内的文件"}
        if not target.exists():
            return {"ok": False, "error": f"不存在：{target.relative_to(root)}", "root": str(root)}
        try:
            limit = max(20, min(int(max_lines or 200), 800))
        except Exception:  # noqa: BLE001
            limit = 200

        if target.is_dir():
            items, total = [], 0
            for p in sorted(target.rglob("*")):
                if any(part in {".git", "node_modules", "__pycache__", ".venv", "dist"}
                       for part in p.parts):
                    continue
                if p.is_file():
                    total += 1
                    if len(items) < 60:
                        items.append(f"{p.relative_to(root)}  ({p.stat().st_size}B)")
            return {"ok": True, "mode": "dir", "path": str(target.relative_to(root)),
                    "files": total, "content": "\n".join(items),
                    "summary": f"目录 {target.relative_to(root)}：{total} 个文件"}

        try:
            size = target.stat().st_size
            if size > 800_000:
                return {"ok": False, "error": f"文件太大（{size}B），请给 focus 缩小范围"}
            text = target.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"读取失败：{type(exc).__name__}: {exc}"}
        lines = text.splitlines()
        rel = str(target.relative_to(root))
        total_lines = len(lines)

        if focus:
            keys = [k.strip() for k in str(focus).replace("，", ",").split(",") if k.strip()]
            hits = [(i, ln) for i, ln in enumerate(lines)
                    if any(k.lower() in ln.lower() for k in keys)]
            if not hits:
                return {"ok": True, "mode": "focus", "path": rel, "lines": total_lines,
                        "content": "", "summary": f"{rel} 中未找到 {focus}"}
            out, last = [], -9
            for i, ln in hits[:20]:
                if i - last > 4:
                    out.append(f"…（第 {i + 1} 行附近）")
                out.append(f"{i + 1:>5}  {ln}")
                last = i
            return {"ok": True, "mode": "focus", "path": rel, "lines": total_lines,
                    "matches": len(hits), "content": "\n".join(out[:limit]),
                    "summary": f"{rel}：{len(hits)} 处匹配「{focus}」"}

        if total_lines <= limit:
            return {"ok": True, "mode": "full", "path": rel, "lines": total_lines,
                    "content": text, "summary": f"{rel}：全文 {total_lines} 行"}
        pat = re.compile(r"^\s*(#|##|def |class |async def |function |export |const |let |var "
                         r"|public |private |interface |type |struct |enum |impl )")
        outline = [f"{i + 1:>5}  {ln}" for i, ln in enumerate(lines) if pat.match(ln)]
        return {"ok": True, "mode": "outline", "path": rel, "lines": total_lines,
                "content": "\n".join(outline[:limit]),
                "summary": f"{rel}：{total_lines} 行（已给结构大纲，需细节请带 focus）"}

    # ---------- write_file：在项目内创建/追加/覆盖文件 ----------
    def write_file(self, path: str = "", content: str = "", mode: str = "create",
                   overwrite: bool = False) -> Dict[str, Any]:
        """安全地写文件：默认只新建；覆盖前自动备份；只允许写在 code_root 以内。"""
        from pathlib import Path

        root = Path(self.code_root).expanduser().resolve()
        if not path:
            return {"ok": False, "error": "需要 path（相对项目根目录）"}
        raw = Path(path).expanduser()
        target = (raw if raw.is_absolute() else (root / raw)).resolve()
        if not str(target).startswith(str(root)):
            return {"ok": False, "error": f"拒绝：{path} 不在允许目录内", "root": str(root)}
        if target.is_dir():
            return {"ok": False, "error": f"{target.relative_to(root)} 是目录，不是文件"}
        data = "" if content is None else str(content)
        if len(data.encode()) > 400_000:
            return {"ok": False, "error": "内容太大（>400KB），请分多次写"}

        exists = target.exists()
        appending = (mode == "append" and exists)
        if exists and not appending and not overwrite:
            return {"ok": False, "exists": True,
                    "error": f"{target.relative_to(root)} 已存在；如要覆盖请显式 overwrite=true",
                    "hint": "覆盖前会自动备份为 <文件名>.bak-<时间戳>"}
        backup = None
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if exists and not appending:
                backup = target.with_name(target.name + f".bak-{int(time.time())}")
                backup.write_bytes(target.read_bytes())
            if appending:
                with open(target, "a", encoding="utf-8") as fh:
                    fh.write(data)
            else:
                target.write_text(data, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"写入失败：{type(exc).__name__}: {exc}"}

        rel = str(target.relative_to(root))
        n_lines = data.count(chr(10)) + (1 if data else 0)
        act = "追加" if appending else ("覆盖" if exists else "新建")
        extra = f"（原文件已备份为 {backup.name}）" if backup else ""
        return {"ok": True, "path": rel, "action": act, "bytes": len(data.encode()),
                "lines": n_lines,
                "backup": str(backup.relative_to(root)) if backup else None,
                "summary": f"{rel}：{act} {n_lines} 行 / {len(data.encode())} 字节{extra}"}

    def run_agent(self, prompt: str, cwd: Optional[str] = None,
                  confirm: bool = False) -> Dict[str, Any]:
        """把需求交给 pi。confirm 不为 True 时**不下发**（只回待确认预览）。"""
        if not confirm:
            return {"ok": False, "needs_confirmation": True, "dispatched": False,
                    "cwd": cwd or os.getcwd(), "prompt_preview": prompt,
                    "message": ("未下发：请先把方案与优劣讲给用户，得到明确同意后，"
                                "再用 confirm=true 重新调用 run_agent。")}
        if self.mode == "rpc" and self.rpc:
            return self._rpc_run(prompt, cwd)
        return self._stub_run(prompt, cwd)

    def _stub_run(self, prompt: str, cwd: Optional[str]) -> Dict[str, Any]:
        jid = "job_" + uuid.uuid4().hex[:8]
        job = Job(id=jid, prompt=prompt, cwd=cwd or os.getcwd(), backend="stub")
        job.status, job.phase = "done", "stub"
        job.artifacts = [self.stub_image] if os.path.exists(self.stub_image) else []
        job.updated_at = time.time()
        self._remember(job)
        return {"ok": True, "job_id": jid, "stub": True,
                "message": "v0 桩任务已完成（未真正调用 pi）"}

    def _rpc_run(self, prompt: str, cwd: Optional[str]) -> Dict[str, Any]:
        jid = "job_" + uuid.uuid4().hex[:8]
        job = Job(id=jid, prompt=prompt, cwd=cwd or (self.rpc.cwd if self.rpc else os.getcwd()),
                  backend="rpc")
        try:
            self.rpc.start()                       # type: ignore[union-attr]
            resp = self.rpc.prompt(prompt, timeout=30)   # type: ignore[union-attr]
            if not resp.get("success"):
                job.status, job.phase = "failed", "rejected"
                job.error = json.dumps(resp.get("error") or resp, ensure_ascii=False)[:300]
                self._remember(job)
                return {"ok": False, "job_id": jid, "error": job.error}
            job.status, job.phase = "running", "pi"
            self._remember(job, activate=True)
            self._emit(f"已下发 pi（job={jid}）：{prompt[:80]}{'…' if len(prompt) > 80 else ''}")
            return {"ok": True, "job_id": jid, "backend": "rpc", "dispatched": True,
                    "message": "已下发给 pi，后台执行中；用 read_status 查进度与产出。"}
        except Exception as exc:  # noqa: BLE001
            job.status, job.phase = "failed", "dispatch_error"
            job.error = f"{type(exc).__name__}: {exc}"
            self._remember(job)
            return {"ok": False, "job_id": jid, "error": job.error}

    def _remember(self, job: Job, activate: bool = False) -> None:
        with self._lock:
            self.jobs[job.id] = job
            self.order.append(job.id)
            if activate:
                self.active = job.id

    # ---------- pi 事件回流 ----------
    def _on_pi_event(self, msg: Dict[str, Any]) -> None:
        with self._lock:
            job = self.jobs.get(self.active) if self.active else None
            if job:
                job.events += 1
                job.updated_at = time.time()
        kind = msg.get("type", "")
        if kind == "tool_execution_start":
            name = msg.get("toolName")
            if job:
                job.tools.append(str(name))
                job.phase = f"tool:{name}"
            args = json.dumps(msg.get("args") or {}, ensure_ascii=False)
            self._emit(f"pi 工具 {name} {args[:100]}")
            if "tool" in self.progress_events:
                self._emit_progress(f"pi 开始执行 {name}")
        elif kind == "message_update":
            ame = msg.get("assistantMessageEvent") or {}
            if ame.get("type") == "text_delta" and ame.get("delta") and job:
                job.last_text = (job.last_text or "") + ame["delta"]
        elif kind == "compaction_start":
            if job:
                job.phase = "compacting"
            self._emit("pi 正在压缩上下文…")
            if "compaction" in self.progress_events:
                self._emit_progress("pi 正在压缩上下文，马上继续")
        elif kind == "auto_retry_start":
            self._emit("pi 触发自动重试（上游限流/5xx）")
            if "retry" in self.progress_events:
                self._emit_progress("pi 遇到上游限流，正在自动重试")
        elif kind == "agent_end":
            if job:
                job.phase = "settling"
        elif kind == "agent_settled":
            if job and job.status == "running":
                job.status, job.phase = "done", "settled"
                job.updated_at = time.time()
                text = (job.last_text or "").strip()
                self._emit("pi 已完成 ✅" + (f"：{text[:100]}" if text else ""))
                if "settled" in self.progress_events:
                    brief = text.replace("\n", " ")[:140]
                    self._emit_progress("pi 已完成本次修改"
                                        + (f"，它的说明是：{brief}" if brief else ""))
                    job.last_text = None       # 同一份结果不重复播报

    # ---------- 状态查询 ----------
    def _rpc_state(self, with_text: bool = True) -> Dict[str, Any]:
        out: Dict[str, Any] = {"alive": False}
        if not self.rpc:
            return out
        try:
            self.rpc.start()                                   # type: ignore[union-attr]
            st = self.rpc.request({"type": "get_state"}, timeout=20)   # type: ignore[union-attr]
            d = st.get("data") or {}
            model = d.get("model") or {}
            out = {
                "alive": self.rpc.alive,                       # type: ignore[union-attr]
                "isStreaming": d.get("isStreaming"),
                "isCompacting": d.get("isCompacting"),
                "model": (f"{model.get('provider')}/{model.get('id')}"
                          if model else None),
                "thinkingLevel": d.get("thinkingLevel"),
                "sessionId": d.get("sessionId"),
                "sessionFile": d.get("sessionFile"),
                "messageCount": d.get("messageCount"),
            }
            gs = self.rpc.request({"type": "get_session_stats"}, timeout=20)   # type: ignore[union-attr]
            gd = gs.get("data") or {}
            out["tokens"] = gd.get("tokens")
            out["cost"] = gd.get("cost")
            out["contextUsage"] = gd.get("contextUsage")
            if with_text and not out.get("isStreaming"):
                lt = self.rpc.request({"type": "get_last_assistant_text"}, timeout=20)  # type: ignore[union-attr]
                out["lastText"] = (lt.get("data") or {}).get("text")
        except Exception as exc:  # noqa: BLE001
            out["error"] = f"{type(exc).__name__}: {exc}"
        return out

    def read_status(self, job_id: Optional[str] = None) -> Dict[str, Any]:
        if self.mode == "rpc" and self.rpc:
            state = self._rpc_state()
            with self._lock:
                job = self.jobs.get(job_id or (self.active or ""))
            if job and state.get("tokens"):
                job.tokens, job.cost = state.get("tokens"), state.get("cost")
                if state.get("lastText"):
                    job.last_text = state["lastText"]
                if job.status == "running" and state.get("isStreaming") is False \
                        and job.phase in ("settling", "done"):
                    job.status, job.phase = "done", "settled"
            return {"ok": True, "pi": state, "job": job.__dict__ if job else None,
                    "jobs_total": len(self.jobs)}
        if job_id and job_id in self.jobs:
            j = self.jobs[job_id]
            return {"ok": True, "job": j.__dict__}
        running = [i for i in self.order if self.jobs[i].status in ("queued", "running")]
        return {
            "ok": True,
            "backend": self.detect(),
            "jobs_total": len(self.jobs),
            "jobs_running": running,
            "recent": [self.jobs[i].__dict__ for i in self.order[-3:]],
        }

    # ---------- 统一分发 ----------
    def dispatch(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if name == "screenshot":
                return self.screenshot(args.get("source", "display"))
            if name == "read_code":
                return self.read_code(args.get("path", ""), args.get("focus", ""),
                                      args.get("max_lines", 200))
            if name == "write_file":
                return self.write_file(args.get("path", ""), args.get("content", ""),
                                       args.get("mode", "create"),
                                       bool(args.get("overwrite", False)))
            if name == "run_agent":
                return self.run_agent(args.get("prompt", ""), args.get("cwd"),
                                      bool(args.get("confirm", False)))
            if name == "read_status":
                return self.read_status(args.get("job_id"))
            if name == "pi_answer":
                return self.answer_pi(args.get("request_id", ""), choice=args.get("choice"),
                                      text=args.get("text"), approved=args.get("approved"),
                                      passphrase=args.get("passphrase"),
                                      cancel=bool(args.get("cancel", False)))
            return {"ok": False, "error": f"unknown tool: {name}"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
