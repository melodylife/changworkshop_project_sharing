# MiniCPM-V 4.7 iOS Demo

一个极简的 iOS 端侧多模态 Demo：**MiniCPM-V 4.7 1B（GGUF）+ llama.cpp-omni**，支持文字 + 图片输入，实时显示端侧推理指标。

> 本仓库只包含代码与编译好的 `llama.xcframework`，**不包含任何模型权重**。模型需自行下载并放入 App 的 Documents 目录。

## 功能

- 本地推理，图片与文字都不离开设备
- **多模型选择**：自动扫描 Documents 下的模型目录，可随时切换
- 支持"固定提示词"模型（例如某个垂直领域微调模型），选中后输入框自动锁定
- 实时指标：TTFT、decode 速度、prefill 速度、token 数、进程内存、模型加载耗时
- 图片输入：相册选择 / 相机拍摄
- 模型文件导入：App 内文件选择、AirDrop、"文件" App、Finder 共享

## 环境要求

| 项 | 版本 |
|---|---|
| Xcode | 16 及以上 |
| iOS | 16.6+ |
| 设备 | iPhone / iPad（真机才能看到有意义的性能数据） |
| 可选工具 | [xcodegen](https://github.com/yonaskolb/XcodeGen)（只在修改 `project.yml` 后需要） |

模拟器可以编译运行，但推理走 CPU，速度没有参考价值。

## 快速开始

```bash
git clone <this-repo>
cd minicpm_ios_demoapp
open MiniCPMDemo.xcodeproj
```

1. 选中 `MiniCPMDemo` target → **Signing & Capabilities** → 选择你自己的 Team（工程默认没有 Team）
2. 如果提示 bundle id 冲突，改成一个你自己的，例如 `com.yourname.minicpmdemo`
3. 选择真机 → Run

如果你修改了 `project.yml`（新增文件、改 bundle id 等），重新生成工程：

```bash
xcodegen generate
```

## 准备模型

需要两个 GGUF 文件：

| 文件 | 说明 | 参考大小 |
|---|---|---|
| 主模型 `*.gguf` | MiniCPM-V 4.7 1B 的 LLM 部分（Q4_K_M） | ~640 MB |
| `mmproj*.gguf` | 视觉编码器 + 投影层（f16） | ~1.0 GB |

推荐直接从官方仓库下载：

- `openbmb/MiniCPM-V-4.7-1B-gguf`（HuggingFace / ModelScope）

### 放到哪里

App 会扫描 `Documents/` 下的**子目录**，一个目录就是一个模型：

```
Documents/
├── MiniCPMV47_1B/
│   ├── MiniCPM-V-4_7-1B-Q4_K_M.gguf
│   └── mmproj-model-f16.gguf
└── MyFinetunedModel/
    ├── my-model-q4_k_m.gguf
    └── mmproj-model-f16.gguf
```

目录名就是 App 里显示的名字。**主模型文件名不能包含 `mmproj`**，否则会被当成视觉编码器。

### 三种导入方式

1. **App 内导入**：左上角菜单 → 导入模型文件 → 同时选中主模型和 mmproj，App 会自动建目录
2. **AirDrop**：传到 iPhone → "文件" App 打开 → 分享到本 App
3. **Finder 文件共享**：iPhone 连接 Mac → Finder → 设备 → 文件 → MiniCPM Demo → 拖入对应目录

> 注意：`UIFileSharingEnabled` 已开启，可以在"文件" App 里直接管理 Documents。

## 使用

1. 打开 App，左上角点开模型菜单，选择模型
2. 如果之前加载过模型，切换后会自动重新加载；否则点"加载模型"
3. 选图（相册或相机）→ 输入问题 → 发送

### 模型菜单

- 模型列表：显示 Documents 下所有"主模型 + mmproj"配对的目录
- 刷新模型列表
- 导入模型文件
- 加载模型 / 清除会话

### 固定提示词模型

如果模型目录名包含 `witcher`（不区分大小写），App 会认为它是垂直领域模型，自动填入固定提示词并禁用输入框。逻辑在 `InferenceViewModel.scanModels()`，可按需修改：

```swift
let isWitcher = dir.lastPathComponent.lowercased().contains("witcher")
defaultPrompt: isWitcher ? Self.witcherPrompt : nil
```

## 指标说明

| 指标 | 含义 |
|---|---|
| TTFT | 从点击发送到第一个 token 的端到端延迟（含图片编码 + prefill） |
| 实时速度 | 最近 12 个 token 的滑动窗口 decode 速度 |
| prefill | 图片 + prompt 的预填充速度 |
| decode | 本轮生成的平均速度 |
| 内存 | 进程 phys_footprint |

## 目录结构

```
MiniCPMDemo/
├── Sources/                 SwiftUI 界面与推理层
│   ├── MiniCPMDemoApp.swift
│   ├── ContentView.swift
│   ├── InferenceViewModel.swift
│   ├── CameraPicker.swift
│   └── Info.plist
├── Wrapper/                 llama.cpp-omni 的 Swift 封装 + ObjC++ 桥接
│   ├── MTMDWrapper.swift
│   ├── MTMDParams.swift
│   ├── MTMDToken.swift
│   ├── MTMDError.swift
│   └── Bridge/
├── Frameworks/
│   └── llama.xcframework    从 llama.cpp-omni 编译（已去除 dSYM 以减小体积）
├── project.yml              xcodegen 工程描述
└── README.md
```

## 常见问题

**Q: 加载模型时报 "Failed to load model"**

先确认文件完整（大小与官方一致），再检查 GGUF 元数据。MiniCPM-V 4.7 的运行时要求存在以下字段：

- `qwen35.attention.recurrent_layers`（数组长度必须等于 `block_count`）
- `qwen35.rope.mrope_time_slot`

自己转换微调模型时，如果缺这些字段，运行时会拒绝加载。官方发布的 GGUF 已包含。

**Q: 模型列表是空的**

Documents 下没有成对的文件。确认每个目录里同时有"主模型 gguf"和"mmproj gguf"，然后点"刷新模型列表"。

**Q: 导入后模型没出现**

导入只会把文件放到目录里，需要回到模型菜单点刷新。

**Q: 模拟器很慢 / 发热**

正常。Metal 推理只在真机上有意义。

**Q: 想换 4× / 16× 视觉压缩**

当前 `MTMDParams` 暴露的是 `imageMaxSliceNums` / `imageMaxTokens`（切片控制）。4×/16× 是 **mmproj 转换时固化的**，需要重新转换 mmproj，运行期不能切换。

## 依赖与许可

- [llama.cpp-omni](https://github.com/OpenBMB/llama.cpp-omni)（MIT）—— 端侧推理引擎，`llama.xcframework` 由其编译
- [MiniCPM-V](https://github.com/OpenBMB/MiniCPM-V)（Apache-2.0）—— 模型与处理器代码
- 模型权重不在本仓库中，使用前请遵守其原始许可

## 声明

本仓库不包含任何 API Key、签名证书、开发者账号信息或个人路径。`llama.xcframework` 为公开开源代码的编译产物。
