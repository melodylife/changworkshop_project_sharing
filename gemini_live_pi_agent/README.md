# 万用搭子 · 实时多模态中继（Gemini Live / Qwen Omni × pi agent）

一个把**浏览器瘦客户端**接到**实时多模态模型**、并桥接**本地 pi agent** 的中继服务。

浏览器只负责采集与播放；API Key、会话状态、工具执行全部留在本机。

## 它能做什么

- **实时语音对话**：原生 audio-to-audio（非 STT→LLM→TTS 级联），支持打断
- **让模型"看见"**：摄像头或屏幕共享，1–6 fps 可调帧率采样
- **验收闭环**：截图 → 指出具体问题 → 按需调用 pi 改代码 → 再截图验收
- **模型自己能动手**：读代码、写文件，或把任务下发给 pi agent 后台执行
- **危险操作要人拍板**：pi 请求确认时用语音口令放行（服务端双重校验）

## 架构

```
手机 / 桌面浏览器          只做采集与播放（不持 Key、不持会话）
        │  WebSocket：JSON 帧，音频/图像走 base64
        ▼
本机中继服务              持 Key · 持会话 · 视觉采样 · 上下文压缩 · 工具执行
        │                                   │
        │ Live 长会话                        │ 工具调用 / 事件回流
        ▼                                   ▼
Gemini Live / Qwen Omni  ←── 语音·图像·文字 ──→  pi agent（RPC 常驻进程）
```

三套上游实现，**对浏览器暴露完全相同的协议**（前端零改动即可切换）：

| 实现 | 启动参数 | 说明 |
|---|---|---|
| Google ADK（默认） | `./run.sh` | `LlmAgent` + `InMemoryRunner.run_live` |
| 裸 WebSocket | `RELAY_APP=server.server:app ./run.sh` | 零额外依赖，排查网络/代理用 |
| Qwen Omni Realtime | `RELAY_APP=server.server_qwen:app ./run.sh` | 阿里云百炼，workspace 维度端点 |

## 快速开始

```bash
# 1) 依赖
python3 -m venv ~/.virtualenv/gemini-live-relay
source ~/.virtualenv/gemini-live-relay/bin/activate
pip install -r requirements.txt

# 2) 凭据（二选一，见 env.example）
export GOOGLE_API_KEY=...          # Gemini（Google AI Studio）
# 或
export DASHSCOPE_API_KEY=...       # Qwen（阿里云百炼）
export QWEN_WORKSPACE=<workspace-id>

# 3) 起服务（自签证书会自动生成在 certs/，不入库）
./run.sh                           # = HTTPS 8443
```

浏览器打开 `https://localhost:8443`。手机端访问局域网 IP 需要信任自签根证书
（脚本用 mkcert 时会把根证书路径打印出来）。

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `GOOGLE_API_KEY` | — | Gemini 凭据（`GEMINI_API_KEY` 亦可） |
| `DASHSCOPE_API_KEY` + `QWEN_WORKSPACE` | — | Qwen 凭据与 workspace 端点 |
| `RELAY_ENV_FILE` | `~/.config/gemini-live-relay/.env` | 凭据文件（环境变量优先） |
| `HTTPS_PROXY` | `http://127.0.0.1:1081` | 访问 Google 的代理；Qwen 直连不走代理 |
| `RELAY_APP` | `server.server_adk:app` | 上游实现选择 |
| `LIVE_MODEL` / `LIVE_VOICE` / `LIVE_LANGUAGE` | — / `Aoede` / `cmn-CN` | 模型、音色、输出语言 |
| `PI_BRIDGE_MODE` | `rpc` | `rpc`（真调 pi）或 `stub`（假任务） |
| `PI_CWD` | 项目根目录 | pi 的工作目录（也是读写工具的沙箱根） |
| `PI_MODEL` / `PI_THINKING` / `PI_RPC_ARGS` | — / `off` / `--approve` | pi 的模型与启动参数 |
| `PI_DIALOG_MODE` / `PI_DIALOG_TIMEOUT` | `ask-user` / `60` | 决策确认策略与超时 |
| `PI_CONFIRM_PHRASE` / `PI_CONFIRM_MODE` | `确认执行` / `transcript` | 口令与校验方式 |
| `RELAY_TERMINAL_LOG` | `0` | `1` = 网页日志同时打到终端 |

## 暴露给模型的工具

| 工具 | 作用 |
|---|---|
| `screenshot` | 取画面（优先返回浏览器最近一帧；无帧时回退桩图） |
| `read_code` | 读文件/目录：给 `focus` 只回匹配片段，大文件回结构大纲 |
| `write_file` | 新建/追加/覆盖文件（默认不覆盖，覆盖前自动备份） |
| `run_agent` | 把需求下发给 pi（**必须先与用户确认**，否则拒绝下发） |
| `read_status` | 回读 pi 状态：是否在跑、tokens、成本、最后一次输出 |
| `pi_answer` | 把用户对 pi 的口头决策回填（confirm 类需口令） |

## 实测踩过的坑（都已在代码里处理）

- **会话时长**：Live API 音视频会话约 2 分钟、纯音频约 15 分钟即断——需要开上下文压缩
- **"1 FPS" 是文档说法**：实测同一串数字按 1/4/12 fps 送入，**4 fps 内每帧都生效**，12 fps 开始丢帧
- **`pi --mode rpc` 分帧只能按 `
` 切**（JSON 字符串里可能有 U+2028/2029）；完成信号要用
  `agent_settled` 而不是 `agent_end`（后者之后还可能有重试或压缩）
- **ADK 2.9.2 的 `RunConfig` 没有 `thinking_level`**：Extended Thinking 需要自己在
  `Gemini.connect` 前注入 `thinking_config`（见 `server/server_adk.py` 的补丁）
- **SSL 背压**：带 timeout 的套接字遇到发送缓冲区满会抛 `BlockingIOError`，
  SSL 层不重试——必须自己 `select` 等待并加写锁，否则一帧就能打崩整条会话
- **语言漂移**：模型默认跟随提问语言，需要显式锁 `languageCode` + 指令
- **Qwen 发图前必须先发过音频**：否则所有图像帧会被丢弃（代码里自动补一小段静音解锁）
- **口令要防误触发**：确认口令必须出现在"这次提问之后"的真实语音转写里

## 目录结构

```
run.sh                启动脚本（http/https、证书生成、环境变量汇总）
personas.json         persona 定义（system prompt + 工具白名单）
server/
  bridge.py           pi 桥接层 + 工具声明（RPC 常驻、决策队列、进度播报）
  live_ws.py          零依赖 WebSocket 客户端（支持 HTTP 代理 CONNECT 隧道）
  keys.py             凭据解析（环境变量优先，文件兜底）
  server_adk.py       Gemini Live（Google ADK 实现）
  server.py           Gemini Live（裸 WebSocket 实现）
  server_qwen.py      Qwen Omni Realtime（百炼实现）
  web/index.html        瘦客户端页面（persona/视觉/帧率/日志面板）
scripts/selfcheck.py  无框架链路冒烟测试
```

## 安全设计

- 凭据只从环境变量或 `RELAY_ENV_FILE` 读取，**代码与日志中不落密钥**
- `certs/` 不入库，由 `run.sh` 首次启动时自动生成
- `read_code` / `write_file` 只允许在 `PI_CWD` 目录内操作，越界直接拒绝
- 覆盖已存在文件前自动生成 `.bak-<时间戳>` 备份
- 危险操作（pi 的安全类确认）默认自动取消，除非用户当面说出口令

## 许可

示例代码，按需取用。
