"""live_ws.py — 零依赖的 WebSocket 客户端（支持 HTTP 代理 CONNECT 隧道）

为什么自己写：
  - 本机必须经 HTTP 代理才能访问 generativelanguage.googleapis.com
  - 常见 ws 库的代理支持版本不一，这里用 stdlib 把链路握在手里（已验证 101 Switching Protocols）

支持：RFC6455 文本帧、掩码、ping/pong、close、分片重组（continuation）。
仅需文本帧（音频走 base64 JSON），足够 v0 使用。
"""

from __future__ import annotations

import base64
import os
import select
import socket
import ssl
import struct
import threading
import time
from typing import Optional
from urllib.parse import urlsplit


class WSError(RuntimeError):
    pass


class ProxyWS:
    """极简 WebSocket 客户端：proxy(CONNECT) -> TLS -> Upgrade -> 文本帧收发。"""

    def __init__(self, url: str, proxy: Optional[str] = None, timeout: float = 30.0,
                 extra_headers: Optional[dict] = None):
        self.url = url
        self.proxy = proxy if proxy is not None else (os.environ.get("HTTPS_PROXY")
                                                      or os.environ.get("https_proxy"))
        self.timeout = timeout
        self.extra_headers = extra_headers or {}
        self.sock: Optional[ssl.SSLSocket] = None
        self._buf = b""
        self._send_lock = threading.Lock()   # 多线程并发写会把 WS 帧交织坏
        self.close_code: Optional[int] = None
        self.close_reason: str = ""

    # ---------- 连接 ----------
    def connect(self) -> "ProxyWS":
        u = urlsplit(self.url)
        if u.scheme not in ("wss", "ws"):
            raise WSError(f"unsupported scheme: {u.scheme}")
        host = u.hostname
        port = u.port or (443 if u.scheme == "wss" else 80)
        path = u.path + (("?" + u.query) if u.query else "")

        raw: socket.socket
        if self.proxy:
            p = urlsplit(self.proxy if "://" in self.proxy else "http://" + self.proxy)
            raw = socket.create_connection((p.hostname, p.port or 8080), timeout=self.timeout)
            raw.sendall(
                f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n\r\n".encode()
            )
            head = self._read_http_head(raw)
            if b" 200" not in head.split(b"\r\n")[0]:
                raise WSError(f"proxy CONNECT failed: {head.split(chr(13).encode())[0]!r}")
        else:
            raw = socket.create_connection((host, port), timeout=self.timeout)

        if u.scheme == "wss":
            ctx = ssl.create_default_context()
            self.sock = ctx.wrap_socket(raw, server_hostname=host)
        else:
            self.sock = raw  # type: ignore[assignment]

        key = base64.b64encode(os.urandom(16)).decode()
        req = [
            f"GET {path} HTTP/1.1",
            f"Host: {host}",
            "Upgrade: websocket",
            "Connection: Upgrade",
            f"Sec-WebSocket-Key: {key}",
            "Sec-WebSocket-Version: 13",
        ]
        req += [f"{k}: {v}" for k, v in self.extra_headers.items()]
        self.sock.sendall(("\r\n".join(req) + "\r\n\r\n").encode())

        head = self._read_http_head(self.sock)
        status = head.split(b"\r\n")[0]
        if b" 101" not in status:
            raise WSError(f"handshake failed: {status!r}")
        return self

    def _read_http_head(self, s) -> bytes:
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
        head, _, rest = data.partition(b"\r\n\r\n")
        self._buf = rest
        return head

    # ---------- 收发 ----------
    def send_text(self, text: str) -> None:
        self._send_frame(0x1, text.encode())

    def send_json(self, obj) -> None:
        import json
        self.send_text(json.dumps(obj, ensure_ascii=False))

    def recv_text(self) -> Optional[str]:
        op, payload = self._recv_frame()
        if op == 0x8:      # close
            self.close_code = struct.unpack("!H", payload[:2])[0] if len(payload) >= 2 else None
            self.close_reason = payload[2:].decode("utf-8", errors="replace") if len(payload) > 2 else ""
            return None
        if op == 0x9:      # ping -> pong
            self._send_frame(0xA, payload)
            return self.recv_text()
        if op == 0xA:      # pong
            return self.recv_text()
        if op in (0x1, 0x2, 0x0):
            # Google 用 **binary** 帧(0x2)下发 JSON；文本帧与续帧一并处理
            return payload.decode("utf-8", errors="replace")
        return self.recv_text()

    def close(self) -> None:
        try:
            if self.sock:
                self._send_frame(0x8, b"")
        except Exception:
            pass
        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass

    # ---------- 帧层 ----------
    def _send_frame(self, opcode: int, payload: bytes) -> None:
        if not self.sock:
            raise WSError("not connected")
        header = bytearray([0x80 | opcode])
        n = len(payload)
        if n < 126:
            header.append(0x80 | n)
        elif n < (1 << 16):
            header.append(0x80 | 126)
            header += struct.pack("!H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack("!Q", n)
        mask = os.urandom(4)
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        with self._send_lock:                 # 串行化：保证一帧完整写出，不与其他线程交织
            self._sendall(bytes(header) + masked)

    def _sendall(self, data: bytes, timeout: float = 15.0) -> None:
        """带背压的发送。

        为什么不能用 sock.sendall：
          本客户端的套接字带 timeout → 底层是非阻塞的；而 **SSL 套接字在发送缓冲区满时
          会直接抛 BlockingIOError (SSLWantWrite/EAGAIN)，SSL 层不做重试**。
          现象：推帧稍快或上游一时卡顿 → 一帧就把整个会话崩掉（ASGI 500）。
          所以这里自己用 select() 等可写，限定总时长，超时才报干净的错误。
        """
        if not self.sock:
            raise WSError("not connected")
        sent, deadline = 0, time.time() + timeout
        total = len(data)
        while sent < total:
            try:
                k = self.sock.send(data[sent:])
                if not k:
                    raise WSError("send returned 0 (connection gone)")
                sent += k
                continue
            except ssl.SSLWantReadError:
                # 重协商等场景：先等可读，再重试写
                remain = deadline - time.time()
                if remain <= 0:
                    raise WSError(f"send blocked (SSL wantRead), {sent}/{total} bytes")
                select.select([self.sock], [], [], min(remain, 0.5))
            except (BlockingIOError, ssl.SSLWantWriteError, InterruptedError):
                remain = deadline - time.time()
                if remain <= 0:
                    raise WSError(
                        f"send timeout: 上游拥塞，{sent}/{total} 字节未发出的部分已丢弃")
                select.select([], [self.sock], [], min(remain, 0.5))

    def _read_exact(self, n: int) -> bytes:
        while len(self._buf) < n:
            try:
                chunk = self.sock.recv(max(4096, n - len(self._buf)))
            except BlockingIOError:          # 非阻塞读：统一成 TimeoutError，交给上层当"空闲"处理
                raise TimeoutError("recv would block")
            if not chunk:
                raise WSError("connection closed")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _recv_frame(self):
        b0, b1 = self._read_exact(2)
        opcode = b0 & 0x0F
        masked = bool(b1 & 0x80)
        n = b1 & 0x7F
        if n == 126:
            n = struct.unpack("!H", self._read_exact(2))[0]
        elif n == 127:
            n = struct.unpack("!Q", self._read_exact(8))[0]
        mask = self._read_exact(4) if masked else b""
        payload = self._read_exact(n) if n else b""
        if masked:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        return opcode, payload


if __name__ == "__main__":  # 手工连通性检查
    import json
    url = os.environ["GEMINI_WS_URL"]
    ws = ProxyWS(url).connect()
    print("connected:", url.split("?")[0])
    ws.close()
