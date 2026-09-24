#!/usr/bin/env bash
# 启动本机中继服务。两种模式都提供：
#   ./run.sh                 等价于 ./run.sh https 8443（默认值，见下方）
#   ./run.sh http            纯 HTTP，直连 IP（无需证书）
#   ./run.sh https           自签/ mkcert 证书，HTTPS
#
# 演示默认值（都可用环境变量覆盖，写在命令前面即可）：
#   上游   Gemini 3.8 Live（ADK 版；RELAY_APP=server.server_qwen:app 切 Qwen 做对比）
#   pi     工作目录默认=本项目、RPC 常驻、--approve
#   日志   终端同步镜像开启（RELAY_TERMINAL_LOG=0 关闭）
#
# 注意：浏览器只在 secure context 下允许摄像头/麦克风。
#   - localhost / 127.0.0.1 视为 secure，可裸 HTTP
#   - 局域网 IP（192.168.x.x）在 **手机浏览器** 上必须 HTTPS
#     （桌面 Chrome 可用 --unsafely-treat-insecure-origin-as-secure 绕过）
set -euo pipefail

MODE="${1:-https}"                        # 默认 HTTPS（手机端必须，否则拿不到摄像头/麦克风）
PORT="${2:-8443}"                         # 默认 8443：8000 被本机 omlx-server 占用
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# ---- 虚拟环境 ----
# 优先使用项目专用 venv：~/.virtualenv/gemini_live_3.8
# 可用 GEMINI_LIVE_VENV 覆盖
VENV="${GEMINI_LIVE_VENV:-$HOME/.virtualenv/gemini_live_3.8}"
if [ ! -x "$VENV/bin/python" ]; then
  if [ -x "$PWD/.venv/bin/python" ]; then
    VENV="$PWD/.venv"
  else
    echo "==> 未找到 venv，创建 $VENV"
    python3 -m venv "$VENV"
  fi
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"
echo "==> venv: $VENV  ($(python -V 2>&1))"
if ! python -c "import fastapi, uvicorn" 2>/dev/null; then
  echo "==> 安装依赖"
  python -m pip install -r requirements.txt
fi

# ---- 代理（供上游访问 Gemini Live 使用）----
export HTTPS_PROXY="${HTTPS_PROXY:-http://127.0.0.1:1081}"
export HTTP_PROXY="${HTTP_PROXY:-$HTTPS_PROXY}"
echo "==> 上游代理: $HTTPS_PROXY"

# ---- pi 桥接（mode=rpc 时真调 pi：常驻 `pi --mode rpc` 进程）----
# 切回假任务：PI_BRIDGE_MODE=stub ./run.sh https 8443
export PI_BRIDGE_MODE="${PI_BRIDGE_MODE:-rpc}"
export PI_MODEL="${PI_MODEL:-deepseek/deepseek-flash}"
export PI_THINKING="${PI_THINKING:-off}"
export PI_CWD="${PI_CWD:-$ROOT}"   # pi 的干活目录（默认本项目；用 PI_CWD=/your/project 切换）
export PI_RPC_ARGS="${PI_RPC_ARGS:---approve}"   # 默认信任项目 .pi/；需要时如 "--approve --no-sandbox"
export PI_DIALOG_MODE="${PI_DIALOG_MODE:-ask-user}"     # ask-user | auto-cancel
export PI_DIALOG_TIMEOUT="${PI_DIALOG_TIMEOUT:-60}"
export PI_CONFIRM_PHRASE="${PI_CONFIRM_PHRASE:-确认执行}"
export PI_CONFIRM_MODE="${PI_CONFIRM_MODE:-transcript}"   # transcript（叠语音转写核对）| model

# ---- Live 模型档位（普通款 / Extended Thinking）----
# 前端可选；环境变量只做默认值与模型 id 覆盖
#   不选/关闭 → gemini-3.8-live（无思考档，传 thinkingLevel 会被 1007 拒）
#   选 low/medium/high → gemini-3.8-live-extended-thinking（必须显式指定档位）
export LIVE_BASE_MODEL="${LIVE_BASE_MODEL:-gemini-3.8-live}"
export LIVE_ET_MODEL="${LIVE_ET_MODEL:-gemini-3.8-live-extended-thinking}"
if [ -n "${LIVE_THINKING-}" ]; then export LIVE_THINKING; fi   # 仅当外部显式设置时作为默认档
echo "==> pi 桥接: mode=$PI_BRIDGE_MODE  model=$PI_MODEL  thinking=$PI_THINKING"
echo "==> pi 决策：${PI_DIALOG_MODE}  ${PI_DIALOG_TIMEOUT}s 超时自动取消 | 口令「${PI_CONFIRM_PHRASE}」(${PI_CONFIRM_MODE})"
echo "==> Live 档位：普通款=${LIVE_BASE_MODEL} | ET=${LIVE_ET_MODEL}（默认档位：${LIVE_THINKING:-关闭}）"
echo "==> pi 工作目录: $PI_CWD  |  额外参数: ${PI_RPC_ARGS:-无}"

# ---- 日志镜像：把网页日志同时打到终端（演示/排查都方便）----
export RELAY_TERMINAL_LOG="${RELAY_TERMINAL_LOG:-1}"    # 0 = 只看网页日志
export PYTHONUNBUFFERED=1                              # 不缓冲，实时刷新
echo "==> 终端日志镜像: ${RELAY_TERMINAL_LOG}（1=开 0=关）"

# ---- 中继实现选择 ----
# RELAY_APP=server.server_adk:app  → Gemini 3.8 Live，基于 Google ADK（默认）
# RELAY_APP=server.server_qwen:app → Qwen 3.5 Omni Realtime（对照实验用）
# RELAY_APP=server.server:app      → Gemini 3.8 Live，裸 WebSocket（排查用）
APP="${RELAY_APP:-server.server_adk:app}"
echo "==> 中继实现: $APP"

LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo 127.0.0.1)"

# ---- 证书 ----
if [ "$MODE" = "https" ]; then
  mkdir -p certs
  if [ ! -f certs/cert.pem ]; then
    if command -v mkcert >/dev/null 2>&1; then
      echo "==> 用 mkcert 生成证书（手机需安装并信任 mkcert 根证书）"
      mkcert -install
      mkcert -cert-file certs/cert.pem -key-file certs/key.pem "$LAN_IP" localhost 127.0.0.1
    else
      echo "==> 用 openssl 生成自签证书（手机需手动信任，否则仍会被拒）"
      openssl req -x509 -newkey rsa:2048 -nodes -days 825 \
        -keyout certs/key.pem -out certs/cert.pem \
        -subj "/CN=$LAN_IP" \
        -addext "subjectAltName=IP:$LAN_IP,IP:127.0.0.1,DNS:localhost"
    fi
  fi
  echo
  echo "  桌面端:  https://localhost:$PORT"
  echo "  手机端:  https://$LAN_IP:$PORT"
  if command -v mkcert >/dev/null 2>&1; then
    echo "  根证书:  $(mkcert -CAROOT)/rootCA.pem   ← AirDrop 到 iPhone 并信任"
    echo "  iPhone 信任: 设置 > 通用 > VPN与设备管理（安装描述文件）"
    echo "              → 设置 > 通用 > 关于本机 > 证书信任设置（打开完全信任）"
  fi
  echo
  exec python -m uvicorn "$APP" --host 0.0.0.0 --port "$PORT" \
    --ssl-keyfile certs/key.pem --ssl-certfile certs/cert.pem
else
  echo
  echo "  桌面端:  http://localhost:$PORT        ← 可用（localhost 视为 secure）"
  echo "  局域网:  http://$LAN_IP:$PORT          ← 桌面 Chrome 可加 flag 绕过"
  echo "  手机端:  ⚠ 裸 HTTP 下浏览器会拒绝摄像头/麦克风，请改用 ./run.sh https"
  echo
  exec python -m uvicorn "$APP" --host 0.0.0.0 --port "$PORT"
fi
