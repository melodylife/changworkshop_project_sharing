import Foundation
import Combine
import SwiftUI
import UIKit

/// 极简 MiniCPM-V 4.7 1B 端侧 Demo 的推理层。
/// 负责：模型加载、图片/文字预处理、流式生成，以及 TTFT / tok/s 等指标。
@MainActor
final class InferenceViewModel: ObservableObject {

    enum Phase: Equatable {
        case noModel
        case loading
        case ready
        case running
        case error(String)

        var text: String {
            switch self {
            case .noModel:  return "未加载模型"
            case .loading:  return "模型加载中…"
            case .ready:    return "就绪"
            case .running:  return "生成中…"
            case .error(let m): return "错误：\(m)"
            }
        }
    }

    // MARK: - 模型常量

    /// 兼容旧版本：默认模型目录
    static let modelDirName = "MiniCPMV47_1B"
    static let modelFileName = "MiniCPM-V-4_7-1B-Q4_K_M.gguf"
    static let mmprojFileName = "mmproj-model-f16.gguf"

    /// 与微调数据完全一致的提示词（选择巫师3模型时自动使用）
    static let witcherPrompt = "这张《巫师3：狂猎》的截图拍的是哪个区域？只回答区域名。"

    struct ModelEntry: Identifiable, Equatable {
        let id: String          // 目录名，作为稳定标识
        let name: String        // 显示名
        let dir: URL
        let modelFile: URL
        let mmprojFile: URL
        let defaultPrompt: String?   // 非 nil 表示该模型锁定提示词
    }

    @Published var availableModels: [ModelEntry] = []
    @Published var selectedModelID: String = UserDefaults.standard.string(forKey: "selectedModelID") ?? ""

    // MARK: - UI 状态

    @Published var phase: Phase = .noModel
    @Published var output: String = ""
    @Published var pickedImage: UIImage?

    // 指标
    @Published var ttftMs: Double?
    @Published var prepMs: Double?
    @Published var liveTps: Double = 0
    @Published var tokenCount: Int = 0
    @Published var prefillTps: Double = 0
    @Published var prefillTokens: Int = 0
    @Published var finalDecodeTps: Double = 0
    @Published var generatedTokens: Int = 0
    @Published var loadSeconds: Double?
    @Published var memoryMB: Double = 0
    @Published var importMessage: String?

    // MARK: - 内部

    let wrapper = MTMDWrapper()
    private var cancellables = Set<AnyCancellable>()
    private var memoryTimer: AnyCancellable?

    private var sendTime: Date?
    private var firstTokenAt: Date?
    private var samples: [(index: Int, at: Date)] = []
    private let windowSize = 12

    var documentsDir: URL {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
    }
    var currentModel: ModelEntry? {
        availableModels.first { $0.id == selectedModelID } ?? availableModels.first
    }

    var modelDir: URL {
        currentModel?.dir ?? documentsDir.appendingPathComponent(Self.modelDirName)
    }
    var modelPath: String { currentModel?.modelFile.path ?? "" }
    var mmprojPath: String { currentModel?.mmprojFile.path ?? "" }

    var modelsPresent: Bool { currentModel != nil }

    var currentModelName: String { currentModel?.name ?? "未发现模型" }

    /// 当前模型锁定的提示词；nil 表示用户可以自由输入
    var lockedPrompt: String? { currentModel?.defaultPrompt }

    var isReady: Bool { phase == .ready }

    // MARK: - Init

    init() {
        bind()
        startMemoryTicker()
        scanModels()
        phase = .noModel   // 文件在，仍需点“加载模型”，避免启动即载入 2GB
    }

    private func bind() {
        wrapper.$fullOutput
            .receive(on: RunLoop.main)
            .sink { [weak self] text in
                self?.output = text
            }
            .store(in: &cancellables)

        wrapper.$currentToken
            .receive(on: RunLoop.main)
            .sink { [weak self] token in
                self?.handleToken(token)
            }
            .store(in: &cancellables)

        wrapper.$generationState
            .receive(on: RunLoop.main)
            .sink { [weak self] state in
                guard let self else { return }
                switch state {
                case .completed:
                    self.finishMetrics()
                    if case .running = self.phase { self.phase = .ready }
                case .failed(let err):
                    self.phase = .error(err.localizedDescription)
                case .cancelled:
                    self.finishMetrics()
                    self.phase = .ready
                default:
                    break
                }
            }
            .store(in: &cancellables)
    }

    private func startMemoryTicker() {
        memoryTimer = Timer.publish(every: 1.0, on: .main, in: .common)
            .autoconnect()
            .sink { [weak self] _ in
                self?.memoryMB = Self.footprintMB()
            }
    }

    // MARK: - 模型管理

    func refreshModelPresence() {
        if modelsPresent {
            if phase == .noModel || isError { phase = .ready }
        } else {
            if phase != .loading { phase = .noModel }
        }
    }

    // MARK: - 模型列表

    /// 扫描 Documents 下所有“主模型 + mmproj”配对的目录，供用户选择
    func scanModels() {
        let fm = FileManager.default
        var found: [ModelEntry] = []
        let dirs = (try? fm.contentsOfDirectory(at: documentsDir,
                                               includingPropertiesForKeys: [.isDirectoryKey],
                                               options: [.skipsHiddenFiles])) ?? []
        for dir in dirs {
            guard (try? dir.resourceValues(forKeys: [.isDirectoryKey]))?.isDirectory == true else { continue }
            let files = (try? fm.contentsOfDirectory(at: dir, includingPropertiesForKeys: nil,
                                                    options: [.skipsHiddenFiles])) ?? []
            let ggufs = files.filter { $0.pathExtension.lowercased() == "gguf" }
            guard let mmproj = ggufs.first(where: { $0.lastPathComponent.lowercased().contains("mmproj") }),
                  let model = ggufs.first(where: { !$0.lastPathComponent.lowercased().contains("mmproj") })
            else { continue }
            let isWitcher = dir.lastPathComponent.lowercased().contains("witcher")
            found.append(ModelEntry(id: dir.lastPathComponent,
                                    name: dir.lastPathComponent,
                                    dir: dir,
                                    modelFile: model,
                                    mmprojFile: mmproj,
                                    defaultPrompt: isWitcher ? Self.witcherPrompt : nil))
        }
        availableModels = found.sorted { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }
        if !availableModels.contains(where: { $0.id == selectedModelID }) {
            selectedModelID = availableModels.first?.id ?? ""
        }
        refreshModelPresence()
    }

    /// 切换模型：停止生成、卸载当前模型；若之前是就绪状态则自动重载新模型
    func selectModel(id: String) {
        guard id != selectedModelID else { return }
        let wasReady = (phase == .ready || phase == .running)
        if phase == .running { stop() }
        selectedModelID = id
        UserDefaults.standard.set(id, forKey: "selectedModelID")
        phase = .loading
        // 关键：必须等 reset 完成再 load，否则会撞上 alreadyInitialized
        Task {
            await wrapper.reset()
            phase = .noModel
            if wasReady { await loadModel() }
        }
    }

    private var isError: Bool {
        if case .error = phase { return true }
        return false
    }

    func loadModel() async {
        guard modelsPresent else {
            phase = .error("缺少模型文件，请先导入")
            return
        }
        guard phase != .loading, phase != .running else { return }

        phase = .loading
        let t0 = Date()
        do {
            let params = MTMDParams(
                modelPath: modelPath,
                mmprojPath: mmprojPath,
                nPredict: 512,
                nCtx: 4096,
                nThreads: 4,
                temperature: 0.7,
                useGPU: true,
                mmprojUseGPU: true,
                warmup: false,
                nUbatch: 0,
                imageMaxSliceNums: -1,
                imageMaxTokens: -1
            )
            try await wrapper.initialize(with: params)
            wrapper.setModelVersion(471)   // V4.7 1B dense
            loadSeconds = Date().timeIntervalSince(t0)
            phase = .ready
        } catch {
            phase = .error(error.localizedDescription)
            importMessage = "模型加载失败：\(error.localizedDescription)"
        }
    }

    // MARK: - 冒烟测试日志

    private func testLog(_ line: String) {
        let url = documentsDir.appendingPathComponent("autotest.log")
        let text = line + "\n"
        guard let data = text.data(using: .utf8) else { return }
        if FileManager.default.fileExists(atPath: url.path), let h = try? FileHandle(forWritingTo: url) {
            h.seekToEndOfFile()
            h.write(data)
            try? h.close()
        } else {
            try? data.write(to: url)
        }
    }

    // MARK: - 推理

    /// 自动化冒烟测试入口：加载模型后跑一轮，指标会 print 到控制台。
    func autoRun(text: String) async {
        try? FileManager.default.removeItem(at: documentsDir.appendingPathComponent("autotest.log"))
        testLog("[START] autoRun")
        await loadModel()
        if case .ready = phase {
            let line = String(format: "[LOAD] %.1f s, mem=%.0f MB", loadSeconds ?? -1, Self.footprintMB())
            print("[AUTORUN] " + line)
            testLog(line)
            await send(text: text)
        } else {
            print("[AUTORUN] load failed: \(phase.text)")
            testLog("[LOAD-FAILED] \(phase.text)")
        }
    }

    func send(text: String) async {
        guard phase == .ready else { return }
        guard modelsPresent else {
            phase = .error("缺少模型文件")
            return
        }

        let raw = lockedPrompt ?? text
        let prompt = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        let finalPrompt = prompt.isEmpty ? "请详细描述这张图片。" : prompt

        // 新一轮：清空 KV，保证 TTFT 指标干净
        wrapper.clearKVCacheForNewTurn()
        resetMetrics()
        output = ""
        phase = .running
        sendTime = Date()

        do {
            var imageFile: String?
            if let image = pickedImage, let url = saveImageForInference(image) {
                imageFile = url.path
            }

            if let imageFile {
                try await wrapper.addImageInBackground(imageFile)
                await wrapper.prewarmAfterImageInBackground()
            }

            try await wrapper.addTextInBackground(finalPrompt, role: "user")

            if let sendTime {
                prepMs = Date().timeIntervalSince(sendTime) * 1000
            }
            try await wrapper.startGeneration()
        } catch {
            phase = .error(error.localizedDescription)
        }
    }

    func stop() {
        wrapper.stopGeneration()
        phase = .ready
    }

    // MARK: - 指标

    private func resetMetrics() {
        ttftMs = nil
        prepMs = nil
        liveTps = 0
        tokenCount = 0
        prefillTps = 0
        prefillTokens = 0
        finalDecodeTps = 0
        generatedTokens = 0
        firstTokenAt = nil
        samples.removeAll()
    }

    private func handleToken(_ token: MTMDToken) {
        guard !token.isEnd, !token.content.isEmpty else { return }
        let now = Date()

        if firstTokenAt == nil {
            firstTokenAt = now
            if let sendTime {
                ttftMs = now.timeIntervalSince(sendTime) * 1000
                let line = String(format: "[TTFT] %.1f ms (prep=%.1f ms)", ttftMs!, prepMs ?? -1)
                print("[METRIC] " + line)
                testLog(line)
            }
        }

        tokenCount += 1
        samples.append((tokenCount, now))
        if samples.count > windowSize + 1 {
            samples.removeFirst(samples.count - (windowSize + 1))
        }
        if let first = samples.first, samples.count >= 3 {
            let dt = now.timeIntervalSince(first.at)
            if dt > 0.05 {
                liveTps = Double(tokenCount - first.index) / dt
            }
        }
    }

    private func finishMetrics() {
        let perf = wrapper.lastPerf
        prefillTokens = Int(perf.prefill_tokens)
        generatedTokens = Int(perf.decode_tokens)
        if perf.prefill_ms > 0 {
            prefillTps = Double(perf.prefill_tokens) / (perf.prefill_ms / 1000.0)
        }
        if perf.decode_ms > 0 {
            finalDecodeTps = Double(perf.decode_tokens) / (perf.decode_ms / 1000.0)
            liveTps = finalDecodeTps
        }
        let line = String(format: "[DONE] prefill_tokens=%d prefill=%.0f tok/s decode_tokens=%d decode=%.2f tok/s mem=%.0f MB",
                          perf.prefill_tokens, prefillTps, perf.decode_tokens, finalDecodeTps, Self.footprintMB())
        print("[METRIC] " + line)
        testLog(line)
    }

    // MARK: - 图片

    private func saveImageForInference(_ image: UIImage) -> URL? {
        let maxSide: CGFloat = 1280
        let size = image.size
        let scale = min(1, maxSide / max(size.width, size.height))
        let target = CGSize(width: size.width * scale, height: size.height * scale)
        let renderer = UIGraphicsImageRenderer(size: target)
        let resized = renderer.image { _ in
            image.draw(in: CGRect(origin: .zero, size: target))
        }
        guard let data = resized.jpegData(compressionQuality: 0.9) else { return nil }
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("minicpm_input_\(Int(Date().timeIntervalSince1970)).jpg")
        do {
            try data.write(to: url, options: .atomic)
            return url
        } catch {
            return nil
        }
    }

    // MARK: - 模型导入（Files / AirDrop）

    func importModelFiles(from urls: [URL]) {
        let fm = FileManager.default
        var copied: [String] = []
        var targetDirName: String?

        func copy(_ url: URL, to dir: URL) -> Bool {
            let scoped = url.startAccessingSecurityScopedResource()
            defer { if scoped { url.stopAccessingSecurityScopedResource() } }
            let dest = dir.appendingPathComponent(url.lastPathComponent)
            do {
                try fm.createDirectory(at: dir, withIntermediateDirectories: true)
                if fm.fileExists(atPath: dest.path) { try fm.removeItem(at: dest) }
                try fm.copyItem(at: url, to: dest)
                copied.append(url.lastPathComponent)
                return true
            } catch {
                importMessage = "复制失败：\(url.lastPathComponent) — \(error.localizedDescription)"
                return false
            }
        }

        // 主模型：每个文件建一个同名目录（便于同时保留 base 与 FT 两套）
        let modelURLs = urls.filter { !$0.lastPathComponent.lowercased().contains("mmproj") }
        let mmprojURLs = urls.filter { $0.lastPathComponent.lowercased().contains("mmproj") }
        for m in modelURLs {
            let stem = m.deletingPathExtension().lastPathComponent
            if copy(m, to: documentsDir.appendingPathComponent(stem)) { targetDirName = stem }
        }
        // mmproj：优先放进同批主模型的目录；单独导入则放进当前模型目录
        for mp in mmprojURLs {
            let dir = targetDirName.map { documentsDir.appendingPathComponent($0) } ?? modelDir
            _ = copy(mp, to: dir)
        }

        if !copied.isEmpty {
            scanModels()
            if let name = targetDirName { selectModel(id: name) }
            importMessage = "已导入：\(copied.joined(separator: ", "))"
        }
    }

    // MARK: - 内存

    static func footprintMB() -> Double {
        var info = task_vm_info_data_t()
        var count = mach_msg_type_number_t(MemoryLayout<task_vm_info_data_t>.size / MemoryLayout<integer_t>.size)
        let result = withUnsafeMutablePointer(to: &info) {
            $0.withMemoryRebound(to: integer_t.self, capacity: Int(count)) {
                task_info(mach_task_self_, task_flavor_t(TASK_VM_INFO), $0, &count)
            }
        }
        guard result == KERN_SUCCESS else { return 0 }
        return Double(info.phys_footprint) / 1024.0 / 1024.0
    }
}
