import SwiftUI

struct ContentView: View {
    @StateObject private var ttsViewModel = TTSViewModel()
    @StateObject private var sttViewModel = STTViewModel()
    @StateObject private var voiceChatViewModel = VoiceChatViewModel()
    @State private var activeTab = 0
    
    var body: some View {
        ZStack {
            // Sleek Dark Background with Gradients
            Color(red: 0.08, green: 0.08, blue: 0.12)
                .ignoresSafeArea()
            
            // Soft Background Glows
            GeometryReader { geo in
                ZStack {
                    Circle()
                        .fill(Color.purple.opacity(0.15))
                        .frame(width: geo.size.width * 0.8)
                        .blur(radius: 80)
                        .position(x: geo.size.width * 0.2, y: geo.size.height * 0.2)
                    
                    Circle()
                        .fill(Color.blue.opacity(0.12))
                        .frame(width: geo.size.width * 0.8)
                        .blur(radius: 80)
                        .position(x: geo.size.width * 0.8, y: geo.size.height * 0.8)
                }
            }
            .ignoresSafeArea()
            
            VStack(spacing: 0) {
                // Header Title
                HeaderView()
                    .padding(.top, 10)
                
                // Custom Tab Bar
                CustomTabBar(activeTab: $activeTab)
                    .padding(.vertical, 16)
                
                // Tab Content
                ScrollView {
                    VStack {
                        if activeTab == 0 {
                            TTSView(viewModel: ttsViewModel)
                                .transition(.opacity.combined(with: .move(edge: .leading)))
                        } else if activeTab == 1 {
                            STTView(viewModel: sttViewModel)
                                .transition(.opacity.combined(with: .move(edge: .trailing)))
                        } else {
                            VoiceChatView(viewModel: voiceChatViewModel)
                                .transition(.opacity.combined(with: .move(edge: .trailing)))
                        }
                    }
                    .padding(.horizontal)
                    .animation(.spring(response: 0.4, dampingFraction: 0.8), value: activeTab)
                }
                
                Spacer()
            }
        }
    }
}

// MARK: - Header
struct HeaderView: View {
    var body: some View {
        VStack(spacing: 4) {
            Text("MLX Audio")
                .font(.system(size: 32, weight: .bold, design: .rounded))
                .foregroundStyle(
                    LinearGradient(
                        colors: [Color.blue, Color.purple, Color.pink],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )
            
            Text("On-Device Speech AI powered by Apple Silicon")
                .font(.system(size: 13, weight: .medium, design: .rounded))
                .foregroundColor(.gray.opacity(0.8))
        }
    }
}

// MARK: - Custom Tab Bar
struct CustomTabBar: View {
    @Binding var activeTab: Int
    
    var body: some View {
        HStack(spacing: 0) {
            TabBarButton(title: "TTS", icon: "bubble.left.and.bubble.right.fill", isActive: activeTab == 0) {
                withAnimation(.spring(response: 0.3, dampingFraction: 0.7)) {
                    activeTab = 0
                }
            }
            
            TabBarButton(title: "STT", icon: "mic.fill", isActive: activeTab == 1) {
                withAnimation(.spring(response: 0.3, dampingFraction: 0.7)) {
                    activeTab = 1
                }
            }
            
            TabBarButton(title: "Voice Chat", icon: "waveform.path.ecg", isActive: activeTab == 2) {
                withAnimation(.spring(response: 0.3, dampingFraction: 0.7)) {
                    activeTab = 2
                }
            }
        }
        .padding(6)
        .background(Color.white.opacity(0.04))
        .cornerRadius(18)
        .padding(.horizontal)
        .overlay(
            RoundedRectangle(cornerRadius: 18)
                .stroke(Color.white.opacity(0.08), lineWidth: 1)
                .padding(.horizontal)
        )
    }
}

struct TabBarButton: View {
    let title: String
    let icon: String
    let isActive: Bool
    let action: () -> Void
    
    var body: some View {
        Button(action: action) {
            HStack(spacing: 8) {
                Image(systemName: icon)
                    .font(.system(size: 14, weight: .semibold))
                Text(title)
                    .font(.system(size: 14, weight: .bold, design: .rounded))
            }
            .foregroundColor(isActive ? .white : .gray)
            .padding(.vertical, 10)
            .frame(maxWidth: .infinity)
            .background(
                ZStack {
                    if isActive {
                        RoundedRectangle(cornerRadius: 14)
                            .fill(
                                LinearGradient(
                                    colors: [Color.blue.opacity(0.6), Color.purple.opacity(0.6)],
                                    startPoint: .topLeading,
                                    endPoint: .bottomTrailing
                                )
                            )
                            .shadow(color: Color.purple.opacity(0.4), radius: 6, x: 0, y: 3)
                    }
                }
            )
        }
    }
}

// MARK: - TTS View
struct TTSView: View {
    @ObservedObject var viewModel: TTSViewModel
    @FocusState private var isInputFocused: Bool
    
    let presets = [
        "Hello from MLX!",
        "Apple Silicon is fast.",
        "On-device models ensure privacy.",
        "Generate natural speech in seconds."
    ]
    
    var body: some View {
        VStack(spacing: 20) {
            // Model Info Card
            ModelCard(
                modelName: "Soprano-80M",
                description: "Lightweight 80M Text-to-Speech model converted for MLX.",
                status: viewModel.statusMessage,
                isActionActive: viewModel.isDownloading
            )
            
            // Text Input Card
            VStack(alignment: .leading, spacing: 12) {
                Text("INPUT TEXT")
                    .font(.system(size: 11, weight: .bold))
                    .foregroundColor(.gray)
                    .tracking(1)
                
                TextEditor(text: $viewModel.text)
                    .font(.system(size: 15, design: .rounded))
                    .foregroundColor(.white)
                    .padding(8)
                    .frame(height: 120)
                    .background(Color.black.opacity(0.3))
                    .cornerRadius(12)
                    .focused($isInputFocused)
                
                // Presets
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        ForEach(presets, id: \.self) { preset in
                            Button(action: {
                                viewModel.text = preset
                            }) {
                                Text(preset)
                                    .font(.system(size: 12, weight: .medium))
                                    .foregroundColor(.white.opacity(0.8))
                                    .padding(.horizontal, 12)
                                    .padding(.vertical, 6)
                                    .background(Color.white.opacity(0.06))
                                    .cornerRadius(20)
                                    .overlay(
                                        RoundedRectangle(cornerRadius: 20)
                                            .stroke(Color.white.opacity(0.12), lineWidth: 1)
                                    )
                            }
                        }
                    }
                }
            }
            .padding()
            .background(Color.white.opacity(0.03))
            .cornerRadius(20)
            .overlay(
                RoundedRectangle(cornerRadius: 20)
                    .stroke(Color.white.opacity(0.06), lineWidth: 1)
            )
            
            // Streaming Toggle Card
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text("STREAMING GENERATION")
                        .font(.system(size: 11, weight: .bold))
                        .foregroundColor(.gray)
                        .tracking(1)
                    Text("Track token generation progress in real-time")
                        .font(.system(size: 12))
                        .foregroundColor(.white.opacity(0.6))
                }
                
                Spacer()
                
                Toggle("", isOn: $viewModel.isStreamingEnabled)
                    .toggleStyle(SwitchToggleStyle(tint: .purple))
                    .labelsHidden()
            }
            .padding()
            .background(Color.white.opacity(0.03))
            .cornerRadius(20)
            .overlay(
                RoundedRectangle(cornerRadius: 20)
                    .stroke(Color.white.opacity(0.06), lineWidth: 1)
            )
            
            // Performance Metrics Card
            if viewModel.isGenerating || viewModel.timeToFirstPlay != nil || viewModel.totalGenerationTime != nil {
                PerformanceMetricsCard(viewModel: viewModel)
            }
            
            // Audio Output Player Card
            if viewModel.generatedAudioURL != nil {
                AudioPlayerCard(viewModel: viewModel)
            }
            
            // Generate Button
            Button(action: {
                isInputFocused = false
                Task {
                    await viewModel.generate()
                }
            }) {
                HStack(spacing: 12) {
                    if viewModel.isGenerating {
                        ProgressView()
                            .progressViewStyle(CircularProgressViewStyle(tint: .white))
                    } else {
                        Image(systemName: "wand.and.stars")
                            .font(.system(size: 16, weight: .bold))
                    }
                    
                    Text(viewModel.isGenerating ? "Generating Audio..." : "Generate Speech")
                        .font(.system(size: 16, weight: .bold, design: .rounded))
                }
                .foregroundColor(.white)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 16)
                .background(
                    LinearGradient(
                        colors: [Color.blue, Color.purple],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )
                .cornerRadius(18)
                .shadow(color: Color.purple.opacity(0.3), radius: 10, x: 0, y: 5)
            }
            .disabled(viewModel.isGenerating || viewModel.isDownloading)
            .opacity((viewModel.isGenerating || viewModel.isDownloading) ? 0.6 : 1.0)
            .padding(.top, 10)
        }
    }
}

// MARK: - STT View
struct STTView: View {
    @ObservedObject var viewModel: STTViewModel
    @State private var waveAnim = false
    
    var body: some View {
        VStack(spacing: 20) {
            // Model Info Card
            ModelCard(
                modelName: "GLM-ASR-Nano",
                description: "Optimized 4-bit ASR Speech-to-Text model (~600M parameters).",
                status: viewModel.statusMessage,
                isActionActive: viewModel.isDownloading
            )
            
            // Recorder Card
            VStack(spacing: 24) {
                Text("MICROPHONE INPUT")
                    .font(.system(size: 11, weight: .bold))
                    .foregroundColor(.gray)
                    .tracking(1)
                
                if viewModel.isRecording {
                    // Recording wave animation
                    HStack(spacing: 4) {
                        ForEach(0..<10) { index in
                            RoundedRectangle(cornerRadius: 3)
                                .fill(LinearGradient(colors: [.red, .orange], startPoint: .top, endPoint: .bottom))
                                .frame(width: 6, height: waveAnim ? CGFloat.random(in: 20...70) : 15)
                        }
                    }
                    .frame(height: 80)
                    .onAppear {
                        withAnimation(Animation.linear(duration: 0.15).repeatForever()) {
                            waveAnim = true
                        }
                    }
                    .onDisappear {
                        waveAnim = false
                    }
                } else if viewModel.isTranscribing {
                    ProgressView()
                        .progressViewStyle(CircularProgressViewStyle(tint: .blue))
                        .scaleEffect(1.5)
                        .frame(height: 80)
                } else {
                    Image(systemName: "waveform.circle.fill")
                        .font(.system(size: 64))
                        .foregroundColor(.blue.opacity(0.6))
                        .frame(height: 80)
                }
                
                // Big Record Button
                Button(action: {
                    Task {
                        if viewModel.isRecording {
                            await viewModel.stopRecording()
                        } else {
                            await viewModel.startRecording()
                        }
                    }
                }) {
                    ZStack {
                        Circle()
                            .fill(viewModel.isRecording ? Color.red : Color.blue)
                            .frame(width: 80, height: 80)
                            .shadow(color: (viewModel.isRecording ? Color.red : Color.blue).opacity(0.4), radius: 10, x: 0, y: 5)
                        
                        Image(systemName: viewModel.isRecording ? "stop.fill" : "mic.fill")
                            .font(.system(size: 30, weight: .bold))
                            .foregroundColor(.white)
                    }
                }
                .disabled(viewModel.isTranscribing || viewModel.isDownloading)
                .opacity((viewModel.isTranscribing || viewModel.isDownloading) ? 0.6 : 1.0)
            }
            .padding(.vertical, 24)
            .frame(maxWidth: .infinity)
            .background(Color.white.opacity(0.03))
            .cornerRadius(20)
            .overlay(
                RoundedRectangle(cornerRadius: 20)
                    .stroke(Color.white.opacity(0.06), lineWidth: 1)
            )
            
            // Transcription Output Card
            VStack(alignment: .leading, spacing: 12) {
                Text("TRANSCRIPTION OUTPUT")
                    .font(.system(size: 11, weight: .bold))
                    .foregroundColor(.gray)
                    .tracking(1)
                
                ScrollView {
                    Text(viewModel.transcription.isEmpty ? (viewModel.isTranscribing ? "Transcribing..." : "No speech transcribed yet. Tap the microphone and speak.") : viewModel.transcription)
                        .font(.system(size: 16, weight: .medium, design: .rounded))
                        .foregroundColor(viewModel.transcription.isEmpty ? .gray : .white)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.vertical, 4)
                }
                .frame(height: 120)
            }
            .padding()
            .background(Color.white.opacity(0.03))
            .cornerRadius(20)
            .overlay(
                RoundedRectangle(cornerRadius: 20)
                    .stroke(Color.white.opacity(0.06), lineWidth: 1)
            )
        }
    }
}

// MARK: - Common Components
struct ModelCard: View {
    let modelName: String
    let description: String
    let status: String
    let isActionActive: Bool
    
    var body: some View {
        HStack(alignment: .top, spacing: 16) {
            ZStack {
                RoundedRectangle(cornerRadius: 14)
                    .fill(Color.blue.opacity(0.1))
                    .frame(width: 50, height: 50)
                
                Image(systemName: "cpu")
                    .font(.system(size: 24, weight: .medium))
                    .foregroundColor(.blue)
            }
            
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text(modelName)
                        .font(.system(size: 17, weight: .bold, design: .rounded))
                        .foregroundColor(.white)
                    
                    Spacer()
                    
                    if isActionActive {
                        ProgressView()
                            .progressViewStyle(CircularProgressViewStyle(tint: .blue))
                    } else {
                        HStack(spacing: 4) {
                            Circle()
                                .fill(Color.green)
                                .frame(width: 6, height: 6)
                            Text("Ready")
                                .font(.system(size: 11, weight: .bold))
                                .foregroundColor(.green)
                        }
                        .padding(.horizontal, 8)
                        .padding(.vertical, 4)
                        .background(Color.green.opacity(0.1))
                        .cornerRadius(8)
                    }
                }
                
                Text(description)
                    .font(.system(size: 13))
                    .foregroundColor(.gray)
                    .lineLimit(2)
                
                Divider()
                    .background(Color.white.opacity(0.08))
                    .padding(.vertical, 4)
                
                Text(status)
                    .font(.system(size: 12, weight: .medium, design: .monospaced))
                    .foregroundColor(.blue.opacity(0.8))
            }
        }
        .padding()
        .background(Color.white.opacity(0.03))
        .cornerRadius(20)
        .overlay(
            RoundedRectangle(cornerRadius: 20)
                .stroke(Color.white.opacity(0.06), lineWidth: 1)
        )
    }
}

struct AudioPlayerCard: View {
    @ObservedObject var viewModel: TTSViewModel
    
    var body: some View {
        HStack(spacing: 16) {
            Button(action: {
                if viewModel.isPlaying {
                    viewModel.stopAudio()
                } else {
                    viewModel.playAudio()
                }
            }) {
                ZStack {
                    Circle()
                        .fill(Color.white.opacity(0.1))
                        .frame(width: 48, height: 48)
                    
                    Image(systemName: viewModel.isPlaying ? "stop.fill" : "play.fill")
                        .font(.system(size: 18, weight: .bold))
                        .foregroundColor(.white)
                }
            }
            
            VStack(alignment: .leading, spacing: 6) {
                Text("TTS Speech Output")
                    .font(.system(size: 15, weight: .bold, design: .rounded))
                    .foregroundColor(.white)
                
                Text("WAV Audio file - mono format")
                    .font(.system(size: 12))
                    .foregroundColor(.gray)
            }
            
            Spacer()
            
            if viewModel.isPlaying {
                // Pulse indicator
                HStack(spacing: 3) {
                    ForEach(0..<4) { index in
                        RoundedRectangle(cornerRadius: 2)
                            .fill(Color.blue)
                            .frame(width: 3, height: 16)
                            .scaleEffect(y: CGFloat.random(in: 0.3...1.0), anchor: .center)
                            .animation(Animation.easeInOut(duration: 0.3).repeatForever(), value: viewModel.isPlaying)
                    }
                }
            }
        }
        .padding()
        .background(Color.white.opacity(0.04))
        .cornerRadius(16)
        .overlay(
            RoundedRectangle(cornerRadius: 16)
                .stroke(Color.white.opacity(0.08), lineWidth: 1)
        )
    }
}


// MARK: - Performance Metrics Components
struct PerformanceMetricsCard: View {
    @ObservedObject var viewModel: TTSViewModel
    
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("PERFORMANCE METRICS")
                .font(.system(size: 11, weight: .bold))
                .foregroundColor(.gray)
                .tracking(1)
            
            HStack(spacing: 10) {
                if viewModel.isStreamingEnabled {
                    MetricItem(
                        icon: "timer",
                        title: "First Play",
                        value: viewModel.timeToFirstPlay.map { String(format: "%.2fs", $0) } ?? (viewModel.isGenerating ? "Timing..." : "--"),
                        color: .purple
                    )
                    
                    MetricItem(
                        icon: "number",
                        title: "Tokens",
                        value: "\(viewModel.generatedTokenCount)",
                        color: .blue
                    )
                    
                    MetricItem(
                        icon: "bolt.fill",
                        title: "Speed",
                        value: viewModel.generationSpeed.map { String(format: "%.1f t/s", $0) } ?? "--",
                        color: .orange
                    )
                } else {
                    MetricItem(
                        icon: "stopwatch.fill",
                        title: "Gen Time",
                        value: viewModel.totalGenerationTime.map { String(format: "%.2fs", $0) } ?? (viewModel.isGenerating ? "Generating..." : "--"),
                        color: .blue
                    )
                    
                    MetricItem(
                        icon: "music.note",
                        title: "Duration",
                        value: viewModel.audioDuration.map { String(format: "%.2fs", $0) } ?? "--",
                        color: .green
                    )
                }
            }
        }
        .padding()
        .background(Color.white.opacity(0.03))
        .cornerRadius(20)
        .overlay(
            RoundedRectangle(cornerRadius: 20)
                .stroke(Color.white.opacity(0.06), lineWidth: 1)
        )
    }
}

struct MetricItem: View {
    let icon: String
    let title: String
    let value: String
    let color: Color
    
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 4) {
                Image(systemName: icon)
                    .font(.system(size: 12))
                    .foregroundColor(color)
                Text(title)
                    .font(.system(size: 10, weight: .bold))
                    .foregroundColor(.gray)
                    .lineLimit(1)
            }
            Text(value)
                .font(.system(size: 15, weight: .bold, design: .rounded))
                .foregroundColor(.white)
                .lineLimit(1)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(10)
        .background(Color.white.opacity(0.02))
        .cornerRadius(12)
        .overlay(
            RoundedRectangle(cornerRadius: 12)
                .stroke(Color.white.opacity(0.04), lineWidth: 1)
        )
    }
}


struct VoiceChatPerformanceMetricsCard: View {
    @ObservedObject var viewModel: VoiceChatViewModel
    
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("PERFORMANCE METRICS")
                .font(.system(size: 11, weight: .bold))
                .foregroundColor(.gray)
                .tracking(1)
            
            HStack(spacing: 10) {
                if viewModel.isStreamingEnabled {
                    MetricItem(
                        icon: "timer",
                        title: "First Play",
                        value: viewModel.timeToFirstPlay.map { String(format: "%.2fs", $0) } ?? (viewModel.isGeneratingTTS ? "Timing..." : "--"),
                        color: .purple
                    )
                    
                    MetricItem(
                        icon: "number",
                        title: "Tokens",
                        value: "\(viewModel.generatedTokenCount)",
                        color: .blue
                    )
                    
                    MetricItem(
                        icon: "bolt.fill",
                        title: "Speed",
                        value: viewModel.generationSpeed.map { String(format: "%.1f t/s", $0) } ?? "--",
                        color: .orange
                    )
                } else {
                    MetricItem(
                        icon: "stopwatch.fill",
                        title: "Gen Time",
                        value: viewModel.totalGenerationTime.map { String(format: "%.2fs", $0) } ?? (viewModel.isGeneratingTTS ? "Generating..." : "--"),
                        color: .blue
                    )
                    
                    MetricItem(
                        icon: "music.note",
                        title: "Duration",
                        value: viewModel.audioDuration.map { String(format: "%.2fs", $0) } ?? "--",
                        color: .green
                    )
                }
            }
        }
        .padding()
        .background(Color.white.opacity(0.03))
        .cornerRadius(20)
        .overlay(
            RoundedRectangle(cornerRadius: 20)
                .stroke(Color.white.opacity(0.06), lineWidth: 1)
        )
    }
}


// MARK: - Voice Chat View
struct VoiceChatView: View {
    @ObservedObject var viewModel: VoiceChatViewModel
    @State private var waveScale: CGFloat = 1.0
    
    var body: some View {
        VStack(spacing: 20) {
            // Model Status Card
            ModelCard(
                modelName: "Gemma3 + GLM + Soprano",
                description: "On-device Voice Assistant loop combining ASR, LLM, and TTS.",
                status: viewModel.statusMessage,
                isActionActive: viewModel.isDownloading
            )
            
            // Chat Conversation History
            VStack(alignment: .leading, spacing: 10) {
                Text("CONVERSATION")
                    .font(.system(size: 11, weight: .bold))
                    .foregroundColor(.gray)
                    .tracking(1)
                    .padding(.horizontal)
                
                ScrollViewReader { proxy in
                    ScrollView {
                        VStack(spacing: 12) {
                            ForEach(viewModel.chatHistory) { message in
                                ChatBubbleView(message: message)
                            }
                            
                            // Streaming LLM Response if active
                            if viewModel.isGeneratingLLM && !viewModel.currentLLMResponse.isEmpty {
                                ChatBubbleView(message: ChatMessage(isUser: false, text: viewModel.currentLLMResponse))
                                    .id("streamingResponse")
                            }
                        }
                        .padding()
                    }
                    .frame(height: 300)
                    .background(Color.black.opacity(0.2))
                    .cornerRadius(16)
                    .onChange(of: viewModel.chatHistory) { _ in
                        withAnimation(.easeOut(duration: 0.3)) {
                            if let lastMessage = viewModel.chatHistory.last {
                                proxy.scrollTo(lastMessage.id, anchor: .bottom)
                            }
                        }
                    }
                    .onChange(of: viewModel.currentLLMResponse) { _ in
                        if viewModel.isGeneratingLLM {
                            proxy.scrollTo("streamingResponse", anchor: .bottom)
                        }
                    }
                }
            }
            .padding(.vertical, 8)
            .background(Color.white.opacity(0.03))
            .cornerRadius(20)
            .overlay(
                RoundedRectangle(cornerRadius: 20)
                    .stroke(Color.white.opacity(0.06), lineWidth: 1)
            )
            
            // Streaming Toggle Card
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text("STREAMING GENERATION")
                        .font(.system(size: 11, weight: .bold))
                        .foregroundColor(.gray)
                        .tracking(1)
                    Text("Track voice token generation in real-time")
                        .font(.system(size: 12))
                        .foregroundColor(.white.opacity(0.6))
                }
                
                Spacer()
                
                Toggle("", isOn: $viewModel.isStreamingEnabled)
                    .toggleStyle(SwitchToggleStyle(tint: .purple))
                    .labelsHidden()
            }
            .padding()
            .background(Color.white.opacity(0.03))
            .cornerRadius(20)
            .overlay(
                RoundedRectangle(cornerRadius: 20)
                    .stroke(Color.white.opacity(0.06), lineWidth: 1)
            )
            
            // Performance Metrics Card
            if viewModel.isGeneratingTTS || viewModel.timeToFirstPlay != nil || viewModel.totalGenerationTime != nil {
                VoiceChatPerformanceMetricsCard(viewModel: viewModel)
            }
            
            // Active Pipeline State display
            if viewModel.isGeneratingLLM || viewModel.isGeneratingTTS || viewModel.isPlaying {
                HStack(spacing: 8) {
                    ProgressView()
                        .progressViewStyle(CircularProgressViewStyle(tint: .purple))
                    Text(pipelineStatusText)
                        .font(.system(size: 13, weight: .semibold, design: .rounded))
                        .foregroundColor(.purple)
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 8)
                .background(Color.purple.opacity(0.1))
                .cornerRadius(12)
            }
            
            // Large Record Button & Help Text
            VStack(spacing: 12) {
                Text(viewModel.isRecording ? "Tap to Finish Speaking" : "Tap and Speak")
                    .font(.system(size: 13, weight: .bold, design: .rounded))
                    .foregroundColor(viewModel.isRecording ? .red : .gray)
                
                Button(action: {
                    Task {
                        if viewModel.isRecording {
                            await viewModel.stopRecording()
                        } else {
                            await viewModel.startRecording()
                        }
                    }
                }) {
                    ZStack {
                        // Pulse rings when recording
                        if viewModel.isRecording {
                            Circle()
                                .stroke(Color.red.opacity(0.3), lineWidth: 3)
                                .frame(width: 100, height: 100)
                                .scaleEffect(waveScale)
                                .opacity(2.0 - Double(waveScale))
                                .onAppear {
                                    withAnimation(Animation.easeInOut(duration: 1.0).repeatForever(autoreverses: false)) {
                                        waveScale = 1.6
                                    }
                                }
                                .onDisappear {
                                    waveScale = 1.0
                                }
                        }
                        
                        Circle()
                            .fill(
                                LinearGradient(
                                    colors: viewModel.isRecording ? [Color.red, Color.orange] : [Color.purple, Color.blue],
                                    startPoint: .topLeading,
                                    endPoint: .bottomTrailing
                                )
                            )
                            .frame(width: 80, height: 80)
                            .shadow(color: (viewModel.isRecording ? Color.red : Color.purple).opacity(0.4), radius: 12, x: 0, y: 6)
                        
                        Image(systemName: viewModel.isRecording ? "stop.fill" : "mic.fill")
                            .font(.system(size: 32, weight: .bold))
                            .foregroundColor(.white)
                    }
                }
                .disabled(viewModel.isDownloading)
                .opacity(viewModel.isDownloading ? 0.5 : 1.0)
            }
            .padding(.vertical, 10)
        }
    }
    
    private var pipelineStatusText: String {
        if viewModel.isGeneratingLLM {
            return "Thinking..."
        } else if viewModel.isGeneratingTTS {
            return "Synthesizing voice response..."
        } else if viewModel.isPlaying {
            return "Speaking..."
        }
        return ""
    }
}

struct ChatBubbleView: View {
    let message: ChatMessage
    
    var body: some View {
        HStack {
            if message.isUser {
                Spacer()
                Text(message.text)
                    .font(.system(size: 14, weight: .medium, design: .rounded))
                    .foregroundColor(.white)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 10)
                    .background(
                        LinearGradient(
                            colors: [Color.blue.opacity(0.8), Color.purple.opacity(0.8)],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                    .clipShape(
                        UnevenRoundedRectangle(
                            cornerRadii: .init(
                                topLeading: 16,
                                bottomLeading: 16,
                                bottomTrailing: 0,
                                topTrailing: 16
                            )
                        )
                    )
            } else {
                Text(message.text)
                    .font(.system(size: 14, weight: .medium, design: .rounded))
                    .foregroundColor(.white)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 10)
                    .background(Color.white.opacity(0.08))
                    .clipShape(
                        UnevenRoundedRectangle(
                            cornerRadii: .init(
                                topLeading: 16,
                                bottomLeading: 0,
                                bottomTrailing: 16,
                                topTrailing: 16
                            )
                        )
                    )
                Spacer()
            }
        }
    }
}

struct ContentView_Previews: PreviewProvider {
    static var previews: some View {
        ContentView()
    }
}
