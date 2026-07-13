# MLXAudioSwift (100% On-Device Voice Assistant)

这是一个在 iOS 模拟器/实机上 100% 本地运行的端侧 AI 语音助手演示项目，基于 Apple 官方的 **MLX** 框架，集成了 语音识别 (ASR)、大语言模型 (LLM) 以及 流式语音合成 (TTS)。

## 🚀 核心功能与架构
- **Speech-to-Text (ASR)**: 使用 `GLM-ASR-Nano-2512-4bit` 对麦克风音频进行本地转录。
- **Language Model (LLM)**: 使用 `Gemma 3` / `Qwen2.5-1.5B` 本地自回归文本生成，集成多轮对话历史上下文记忆。
- **Text-to-Speech (TTS)**: 使用 `Soprano-80M-bf16` 声学模型流式输出合成音频，实现毫秒级首播延迟。
- **统一内存架构 (UMA) 优化**: 基于 Apple Silicon Metal GPU 加速，避免冗余的显存拷贝，常驻内存仅需 ~450MB-600MB，极度省电且高效。

## 📦 本地运行准备（下载模型权重）
由于 Hugging Face 上的 `.safetensors` 模型权重体积较大，我们已在 `.gitignore` 中忽略了此类大文件以防止 GitHub 上传超重。在运行本项目前，请先下载以下模型文件并将权重放入对应的 `.bundle` 子目录中：

1. **GLM-ASR-Nano-2512-4bit**:
   - 从 [mlx-community/GLM-ASR-Nano-2512-4bit](https://huggingface.co/mlx-community/GLM-ASR-Nano-2512-4bit) 下载 `model.safetensors` 并将其放入 `MLXAudioSwift/GLM-ASR-Nano-2512-4bit.bundle/`。
2. **Soprano-80M-bf16**:
   - 从 [mlx-community/Soprano-80M-bf16](https://huggingface.co/mlx-community/Soprano-80M-bf16) 下载 `model.safetensors` 并将其放入 `MLXAudioSwift/Soprano-80M-bf16.bundle/`。
3. **Gemma-3-4bit / Qwen2.5-4bit**:
   - 从 [mlx-community/gemma-3-4bit](https://huggingface.co/mlx-community/gemma-3-4bit) 下载 `model.safetensors` 并将其放入 `MLXAudioSwift/gemma3.bundle/`。

## 🛠️ 构建与调试
1. 用 Xcode 16+ 打开 `MLXAudioSwift.xcodeproj`。
2. 连接真机 iPhone，或选择 iOS Simulator 作为运行目标。
3. 按下 **`Cmd + R`** 构建并运行。
4. **演示 GPU Compute 占用**：
   - 必须运行在 **真机 iPhone** 上。
   - 在 Xcode 左侧调试导航栏 (Debug Navigator, `Cmd + 7`) 中点击 **GPU**（不是 FPS 仪表盘），即可在 LLM 生成或 TTS 合成时看到 GPU Compute 占比飙升至 **70%-95%** 的震撼实时效果。
