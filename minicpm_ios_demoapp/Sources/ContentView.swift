import SwiftUI
import PhotosUI

struct ContentView: View {
    @StateObject private var vm = InferenceViewModel()
    @State private var prompt: String = ""
    @State private var photoItem: PhotosPickerItem?
    @State private var showImporter = false
    @State private var showCamera = false

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                metricsBar
                Divider()
                outputView
                Divider()
                composer
            }
            .navigationTitle("MiniCPM-V 4.7 · 1B")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Menu {
                        Section("模型（\(vm.availableModels.count)）") {
                            if vm.availableModels.isEmpty {
                                Text("未发现模型，请先导入")
                            }
                            ForEach(vm.availableModels) { m in
                                Button {
                                    vm.selectModel(id: m.id)
                                } label: {
                                    if m.id == vm.selectedModelID {
                                        Label(m.name, systemImage: "checkmark")
                                    } else {
                                        Text(m.name)
                                    }
                                }
                            }
                        }
                        Divider()
                        Button("刷新模型列表") { vm.scanModels() }
                        Button("导入模型文件…") { showImporter = true }
                        Button("加载模型") { Task { await vm.loadModel() } }
                        Button("清除会话", role: .destructive) {
                            vm.output = ""
                            vm.pickedImage = nil
                            Task { await vm.wrapper.reset(); vm.phase = .noModel; vm.refreshModelPresence() }
                        }
                    } label: {
                        HStack(spacing: 4) {
                            Image(systemName: "cube.box")
                            Text(vm.currentModelName)
                                .lineLimit(1)
                                .frame(maxWidth: 140, alignment: .leading)
                        }
                        .font(.caption)
                    }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    statusBadge
                }
            }
            .onChange(of: vm.selectedModelID) { _ in
                prompt = vm.lockedPrompt ?? ""
            }
            .onAppear { if vm.lockedPrompt != nil { prompt = vm.lockedPrompt! } }
            .task {
                if (ProcessInfo.processInfo.arguments.contains("-autoRun") || ProcessInfo.processInfo.arguments.contains("autoRun")) {
                    await vm.autoRun(text: "请用一句话介绍你自己。")
                }
            }
            .onChange(of: photoItem) { item in
                guard let item else { return }
                Task {
                    if let data = try? await item.loadTransferable(type: Data.self),
                       let image = UIImage(data: data) {
                        vm.pickedImage = image
                    }
                }
            }
            .fullScreenCover(isPresented: $showCamera) {
                CameraPicker { image in
                    vm.pickedImage = image
                }
                .ignoresSafeArea()
            }
            .fileImporter(
                isPresented: $showImporter,
                allowedContentTypes: [.data],
                allowsMultipleSelection: true
            ) { result in
                if case .success(let urls) = result {
                    vm.importModelFiles(from: urls)
                }
            }
            .alert("模型", isPresented: Binding(
                get: { vm.importMessage != nil },
                set: { if !$0 { vm.importMessage = nil } }
            )) {
                Button("好") { vm.importMessage = nil }
            } message: {
                Text(vm.importMessage ?? "")
            }
        }
    }

    // MARK: - 指标栏

    private var metricsBar: some View {
        VStack(spacing: 10) {
            HStack(spacing: 10) {
                metric("TTFT", value: vm.ttftMs.map { String(format: "%.0f ms", $0) } ?? "—", tint: .orange)
                metric("实时速度", value: vm.liveTps > 0 ? String(format: "%.1f tok/s", vm.liveTps) : "—", tint: .green)
                metric("生成 tokens", value: vm.tokenCount > 0 ? "\(vm.tokenCount)" : "—", tint: .blue)
                metric("内存", value: vm.memoryMB > 0 ? String(format: "%.0f MB", vm.memoryMB) : "—", tint: .purple)
            }
            HStack(spacing: 10) {
                metric("预处理", value: vm.prepMs.map { String(format: "%.0f ms", $0) } ?? "—", tint: .gray)
                metric("prefill", value: vm.prefillTps > 0 ? String(format: "%.0f tok/s", vm.prefillTps) : "—", tint: .gray)
                metric("decode(本轮)", value: vm.finalDecodeTps > 0 ? String(format: "%.1f tok/s", vm.finalDecodeTps) : "—", tint: .gray)
                metric("加载", value: vm.loadSeconds.map { String(format: "%.1f s", $0) } ?? "—", tint: .gray)
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .background(Color(.secondarySystemBackground))
    }

    private func metric(_ title: String, value: String, tint: Color) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title)
                .font(.system(size: 10, weight: .medium))
                .foregroundStyle(.secondary)
            Text(value)
                .font(.system(size: 13, weight: .semibold, design: .monospaced))
                .foregroundStyle(tint)
                .lineLimit(1)
                .minimumScaleFactor(0.7)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    // MARK: - 状态

    private var statusBadge: some View {
        HStack(spacing: 6) {
            Circle()
                .fill(statusColor)
                .frame(width: 8, height: 8)
            Text(vm.phase.text)
                .font(.caption2)
                .foregroundStyle(.secondary)
                .lineLimit(1)
        }
    }

    private var statusColor: Color {
        switch vm.phase {
        case .ready: return .green
        case .running: return .orange
        case .loading: return .yellow
        case .error: return .red
        case .noModel: return .gray
        }
    }

    // MARK: - 输出

    private var outputView: some View {
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 8) {
                    if vm.output.isEmpty {
                        Text(vm.modelsPresent
                             ? "模型文件已就绪，点右上角菜单加载模型，然后选择图片或直接提问。"
                             : "还没有模型文件。把 \(InferenceViewModel.modelFileName) 和 \(InferenceViewModel.mmprojFileName) 放到 App 的 Documents/\(InferenceViewModel.modelDirName)/，或用菜单里的“导入模型文件…”。")
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                            .padding(.top, 24)
                    } else {
                        Text(vm.output)
                            .font(.system(size: 15))
                            .textSelection(.enabled)
                    }
                    Color.clear.frame(height: 1).id("bottom")
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(16)
            }
            .onChange(of: vm.output) { _ in
                withAnimation(.linear(duration: 0.1)) { proxy.scrollTo("bottom", anchor: .bottom) }
            }
        }
    }

    // MARK: - 输入区

    private var composer: some View {
        VStack(spacing: 10) {
            if let image = vm.pickedImage {
                HStack(spacing: 10) {
                    Image(uiImage: image)
                        .resizable()
                        .scaledToFill()
                        .frame(width: 64, height: 64)
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                    Text("已选择图片")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                    Spacer()
                    Button {
                        vm.pickedImage = nil
                        photoItem = nil
                    } label: {
                        Image(systemName: "xmark.circle.fill")
                            .foregroundStyle(.secondary)
                    }
                }
                .padding(.horizontal, 16)
            }

            HStack(spacing: 10) {
                Button {
                    showCamera = true
                } label: {
                    Image(systemName: "camera")
                        .font(.system(size: 20))
                        .frame(width: 40, height: 40)
                        .background(Color(.secondarySystemBackground))
                        .clipShape(RoundedRectangle(cornerRadius: 10))
                }

                PhotosPicker(selection: $photoItem, matching: .images) {
                    Image(systemName: "photo")
                        .font(.system(size: 20))
                        .frame(width: 40, height: 40)
                        .background(Color(.secondarySystemBackground))
                        .clipShape(RoundedRectangle(cornerRadius: 10))
                }

                TextField(vm.lockedPrompt == nil ? "问点什么…" : "该模型固定提示词：识别截图所属区域",
                          text: $prompt, axis: .vertical)
                    .disabled(vm.lockedPrompt != nil)
                    .lineLimit(1...4)
                    .textFieldStyle(.plain)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 9)
                    .background(Color(.secondarySystemBackground))
                    .clipShape(RoundedRectangle(cornerRadius: 10))

                if vm.phase == .running {
                    Button {
                        vm.stop()
                    } label: {
                        Image(systemName: "stop.fill")
                            .font(.system(size: 18))
                            .frame(width: 44, height: 44)
                            .background(Color.red)
                            .foregroundStyle(.white)
                            .clipShape(RoundedRectangle(cornerRadius: 10))
                    }
                } else {
                    Button {
                        Task {
                            await vm.send(text: prompt)
                            prompt = ""
                        }
                    } label: {
                        Image(systemName: "arrow.up")
                            .font(.system(size: 18, weight: .bold))
                            .frame(width: 44, height: 44)
                            .background(vm.isReady ? Color.accentColor : Color.gray.opacity(0.4))
                            .foregroundStyle(.white)
                            .clipShape(RoundedRectangle(cornerRadius: 10))
                    }
                    .disabled(!vm.isReady)
                }
            }
            .padding(.horizontal, 16)
            .padding(.bottom, 8)
        }
        .padding(.top, 8)
        .background(.bar)
    }
}

#Preview {
    ContentView()
}
