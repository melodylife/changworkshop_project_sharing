import Foundation
import Combine
import MLX
import MLXAudioCore
import MLXAudioSTT
import MLXAudioTTS
import MLXLLM
import MLXLMCommon
import AVFoundation
import HuggingFace
import Tokenizers

struct ChatMessage: Identifiable, Equatable {
    let id = UUID()
    let isUser: Bool
    let text: String
}

@MainActor
class VoiceChatViewModel: ObservableObject {
    @Published var chatHistory: [ChatMessage] = [
        ChatMessage(isUser: false, text: "Hello! I am your on-device AI voice assistant. Tap the microphone below and ask me anything.")
    ]
    @Published var isDownloading = false
    @Published var isRecording = false
    @Published var isGeneratingLLM = false
    @Published var isGeneratingTTS = false
    @Published var isPlaying = false
    @Published var statusMessage: String = "Ready"
    @Published var currentLLMResponse: String = ""
    
    // Performance metrics
    @Published var isStreamingEnabled = false
    @Published var generatedTokenCount = 0
    @Published var timeToFirstPlay: Double? = nil
    @Published var totalGenerationTime: Double? = nil
    @Published var generationSpeed: Double? = nil
    @Published var audioDuration: Double? = nil
    
    private var sttModel: GLMASRModel?
    private var llmContainer: ModelContainer?
    private var llmSession: ChatSession?
    private var ttsModel: SopranoModel?
    
    private var audioRecorder: AVAudioRecorder?
    private var audioPlayer: AVAudioPlayer?
    private var recordingURL: URL?
    private var generatedAudioURL: URL?
    private var timer: Timer?
    private var generationStartTime: Double = 0
    
    func loadModels() async {
        guard sttModel == nil || llmContainer == nil || ttsModel == nil else { return }
        
        isDownloading = true
        statusMessage = "Loading voice chat models..."
        
        do {
            // 1. Load Speech-to-Text model
            if sttModel == nil {
                statusMessage = "Loading Speech-to-Text model (GLM-ASR)..."
                var modelURL: URL? = nil
                if let nestedURL = Bundle.main.url(forResource: "GLM-ASR-Nano-2512-4bit", withExtension: "bundle") {
                    modelURL = nestedURL
                } else if let nestedURL = Bundle.main.url(forResource: "GLM-ASR-Nano-2512-4bit", withExtension: nil) {
                    modelURL = nestedURL
                }
                
                if let url = modelURL {
                    sttModel = try await GLMASRModel.fromModelDirectory(url)
                } else {
                    sttModel = try await GLMASRModel.fromPretrained("mlx-community/GLM-ASR-Nano-2512-4bit")
                }
            }
            
            // 2. Load LLM model
            if llmContainer == nil {
                statusMessage = "Loading LLM (Gemma3)..."
                var modelURL: URL? = nil
                
                // Check if folder exists in bundle (as bundle or nested group)
                if let nestedURL = Bundle.main.url(forResource: "gemma3", withExtension: "bundle") {
                    modelURL = nestedURL
                    statusMessage = "Loading bundled LLM model..."
                } else if let nestedURL = Bundle.main.url(forResource: "gemma3", withExtension: nil) {
                    modelURL = nestedURL
                    statusMessage = "Loading bundled LLM model..."
                }
                
                if let url = modelURL {
                    llmContainer = try await loadModelContainer(
                        from: url,
                        using: TransformersLoader()
                    )
                } else {
                    statusMessage = "Downloading and loading LLM from HF..."
                    llmContainer = try await loadModelContainer(
                        from: HubBridge(HuggingFace.HubClient()),
                        using: TransformersLoader(),
                        id: "mlx-community/gemma3"
                    )
                }
                
                if let container = llmContainer {
                    await container.update { context in
                        context.configuration.extraEOSTokens.insert("<|im_end|>")
                        context.configuration.extraEOSTokens.insert("<end_of_turn>")
                    }
                    
                    var gp = GenerateParameters()
                    gp.maxTokens = 100 // Limit response length for voice chat
                    gp.temperature = 0.7
                    
                    llmSession = ChatSession(
                        container,
                        instructions: "You are a helpful, friendly, and conversational on-device voice assistant. Answer the user directly as a person. Keep your responses brief and conversational (1-3 sentences).",
                        generateParameters: gp
                    )
                }
            }
            
            // 3. Load Text-to-Speech model
            if ttsModel == nil {
                statusMessage = "Loading Text-to-Speech model (Soprano)..."
                var modelURL: URL? = nil
                if let nestedURL = Bundle.main.url(forResource: "Soprano-80M-bf16", withExtension: "bundle") {
                    modelURL = nestedURL
                } else if let nestedURL = Bundle.main.url(forResource: "Soprano-80M-bf16", withExtension: nil) {
                    modelURL = nestedURL
                }
                
                if let url = modelURL {
                    ttsModel = try await SopranoModel.fromModelDirectory(url, repo: "mlx-community/Soprano-80M-bf16")
                } else {
                    ttsModel = try await SopranoModel.fromPretrained("mlx-community/Soprano-80M-bf16")
                }
            }
            
            statusMessage = "Ready for Voice Chat"
        } catch {
            statusMessage = "Error loading models: \(error.localizedDescription)"
            print("VoiceChat Model Load Error: \(error)")
        }
        isDownloading = false
    }
    
    func startRecording() async {
        if sttModel == nil || llmContainer == nil || ttsModel == nil {
            await loadModels()
        }
        
        guard sttModel != nil && llmContainer != nil && ttsModel != nil else {
            statusMessage = "Please wait for models to load."
            return
        }
        
        // Check microphone permission
        let session = AVAudioSession.sharedInstance()
        let permission = await withCheckedContinuation { continuation in
            session.requestRecordPermission { granted in
                continuation.resume(returning: granted)
            }
        }
        
        guard permission else {
            statusMessage = "Microphone permission denied."
            return
        }
        
        stopAudio()
        
        do {
            try session.setCategory(.record, mode: .measurement, options: [])
            try session.setActive(true)
            
            let tempDir = FileManager.default.temporaryDirectory
            let fileURL = tempDir.appendingPathComponent("voice_chat_input.wav")
            self.recordingURL = fileURL
            
            // Remove old input if exists
            if FileManager.default.fileExists(atPath: fileURL.path) {
                try? FileManager.default.removeItem(at: fileURL)
            }
            
            let settings: [String: Any] = [
                AVFormatIDKey: Int(kAudioFormatLinearPCM),
                AVSampleRateKey: 16000.0,
                AVNumberOfChannelsKey: 1,
                AVLinearPCMBitDepthKey: 16,
                AVLinearPCMIsBigEndianKey: false,
                AVLinearPCMIsFloatKey: false
            ]
            
            audioRecorder = try AVAudioRecorder(url: fileURL, settings: settings)
            audioRecorder?.prepareToRecord()
            audioRecorder?.record()
            
            isRecording = true
            statusMessage = "Listening..."
            currentLLMResponse = ""
        } catch {
            statusMessage = "Recording error: \(error.localizedDescription)"
            print("VoiceChat Recording Error: \(error)")
        }
    }
    
    func stopRecording() async {
        audioRecorder?.stop()
        isRecording = false
        statusMessage = "Processing speech..."
        
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        
        await processVoiceInput()
    }
    
    private func processVoiceInput() async {
        guard let url = recordingURL, let sttModel = sttModel, let llmSession = llmSession, let ttsModel = ttsModel else {
            statusMessage = "Error: Models or recording not ready"
            return
        }
        
        do {
            // 1. Speech-to-Text (Transcribe)
            statusMessage = "Transcribing speech..."
            let (_, audioData) = try loadAudioArray(from: url, sampleRate: 16000)
            
            let transcriptionResult = try await Task.detached(priority: .userInitiated) {
                sttModel.generate(audio: audioData)
            }.value
            
            let userQuery = transcriptionResult.text.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !userQuery.isEmpty else {
                statusMessage = "Didn't catch that. Tap the mic and try again."
                return
            }
            
            // Add user query to history
            chatHistory.append(ChatMessage(isUser: true, text: userQuery))
            
            // 2. LLM Text Generation
            isGeneratingLLM = true
            statusMessage = "Thinking..."
            
            // Re-create the session with full conversation history to provide memory
            if let container = llmContainer {
                var gp = GenerateParameters()
                gp.maxTokens = 100 // Limit response length for voice chat
                gp.temperature = 0.7
                
                // Drop the first message (initial assistant greeting) because templates like Gemma 3
                // strictly require the conversation history to start with a user message.
                // Drop the last message because it's the current user query, which is passed to streamResponse().
                let mlxHistory = chatHistory.dropFirst().dropLast().map { msg in
                    return msg.isUser ? MLXLMCommon.Chat.Message.user(msg.text) : MLXLMCommon.Chat.Message.assistant(msg.text)
                }
                
                self.llmSession = ChatSession(
                    container,
                    instructions: "You are a helpful, friendly, and conversational on-device voice assistant. Answer the user directly as a person. Keep your responses brief and conversational (1-3 sentences).",
                    history: mlxHistory,
                    generateParameters: gp
                )
            }
            
            guard let activeSession = self.llmSession else {
                statusMessage = "Error: LLM Session not initialized"
                return
            }
            
            let stream = activeSession.streamResponse(to: userQuery, role: .user, images: [], videos: [])
            var fullResponse = ""
            for try await chunk in stream {
                fullResponse += chunk
                currentLLMResponse = fullResponse
                statusMessage = "Generating reply..."
            }
            
            // Append assistant response to history
            chatHistory.append(ChatMessage(isUser: false, text: fullResponse))
            currentLLMResponse = ""
            isGeneratingLLM = false
            
            // 3. Text-to-Speech synthesis
            isGeneratingTTS = true
            statusMessage = "Synthesizing voice..."
            
            // Reset metrics
            generatedTokenCount = 0
            timeToFirstPlay = nil
            totalGenerationTime = nil
            generationSpeed = nil
            audioDuration = nil
            let generationStartTime = CFAbsoluteTimeGetCurrent()
            self.generationStartTime = generationStartTime
            
            let parameters = GenerateParameters(
                maxTokens: 400,
                temperature: 0.7,
                topP: 0.95
            )
            
            var finalAudio: MLXArray?
            let textToGenerate = fullResponse
            let modelRef = ttsModel
            
            if isStreamingEnabled {
                statusMessage = "Streaming tokens..."
                let stream = modelRef.generateStream(
                    text: textToGenerate,
                    voice: nil,
                    refAudio: nil,
                    refText: nil,
                    language: nil,
                    generationParameters: parameters
                )
                
                for try await event in stream {
                    switch event {
                    case .token(_):
                        generatedTokenCount += 1
                        statusMessage = "Generating: \(generatedTokenCount) tokens..."
                    case .info(let info):
                        print("Stream info: \(info.summary)")
                        generationSpeed = info.tokensPerSecond
                    case .audio(let audio):
                        finalAudio = audio
                    }
                }
            } else {
                statusMessage = "Generating speech..."
                let audio = try await Task.detached(priority: .userInitiated) {
                    try await modelRef.generate(text: textToGenerate, parameters: parameters)
                }.value
                finalAudio = audio
            }
            
            guard let audio = finalAudio else {
                throw NSError(domain: "VoiceChat", code: 500, userInfo: [NSLocalizedDescriptionKey: "Failed to generate audio"])
            }
            
            // Save output WAV
            let tempDir = FileManager.default.temporaryDirectory
            let outputURL = tempDir.appendingPathComponent("voice_chat_output.wav")
            if FileManager.default.fileExists(atPath: outputURL.path) {
                try? FileManager.default.removeItem(at: outputURL)
            }
            
            let samples = audio.asArray(Float.self)
            try AudioUtils.writeWavFile(samples: samples, sampleRate: Double(ttsModel.sampleRate), fileURL: outputURL)
            self.generatedAudioURL = outputURL
            self.audioDuration = Double(samples.count) / Double(ttsModel.sampleRate)
            
            if !isStreamingEnabled {
                totalGenerationTime = CFAbsoluteTimeGetCurrent() - generationStartTime
            }
            
            statusMessage = "Speaking..."
            
            // 4. Playback
            playAudio()
            
            isGeneratingTTS = false
        } catch {
            statusMessage = "Error: \(error.localizedDescription)"
            isGeneratingLLM = false
            isGeneratingTTS = false
            print("VoiceChat pipeline error: \(error)")
        }
    }
    
    func playAudio() {
        guard let url = generatedAudioURL else { return }
        
        let session = AVAudioSession.sharedInstance()
        do {
            try session.setCategory(.playback, mode: .default, options: [])
            try session.setActive(true)
            
            audioPlayer = try AVAudioPlayer(contentsOf: url)
            audioPlayer?.prepareToPlay()
            audioPlayer?.play()
            isPlaying = true
            
            if isStreamingEnabled && timeToFirstPlay == nil && isGeneratingTTS && generationStartTime > 0 {
                timeToFirstPlay = CFAbsoluteTimeGetCurrent() - generationStartTime
            }
            
            timer?.invalidate()
            timer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] timer in
                guard let self = self else {
                    timer.invalidate()
                    return
                }
                Task { @MainActor in
                    if let player = self.audioPlayer, !player.isPlaying {
                        self.isPlaying = false
                        self.statusMessage = "Ready"
                        self.timer?.invalidate()
                        self.timer = nil
                    }
                }
            }
        } catch {
            statusMessage = "Playback error: \(error.localizedDescription)"
            print("VoiceChat Playback Error: \(error)")
        }
    }
    
    func stopAudio() {
        audioPlayer?.stop()
        isPlaying = false
        timer?.invalidate()
        timer = nil
        statusMessage = "Ready"
    }
}

// MARK: - Downloader & Tokenizer Adapters

private struct HubBridge: Downloader {
    private let upstream: HuggingFace.HubClient

    init(_ upstream: HuggingFace.HubClient) {
        self.upstream = upstream
    }

    public func download(
        id: String,
        revision: String?,
        matching patterns: [String],
        useLatest: Bool,
        progressHandler: @Sendable @escaping (Progress) -> Void
    ) async throws -> URL {
        guard let repoID = Repo.ID(rawValue: id) else {
            throw NSError(domain: "VoiceChat", code: 400, userInfo: [NSLocalizedDescriptionKey: "Invalid repo ID: \(id)"])
        }
        let revision = revision ?? "main"

        return try await upstream.downloadSnapshot(
            of: repoID,
            revision: revision,
            matching: patterns,
            progressHandler: { @MainActor progress in
                progressHandler(progress)
            }
        )
    }
}

private struct TokenizerBridge: MLXLMCommon.Tokenizer {
    private let upstream: any Tokenizers.Tokenizer

    init(_ upstream: any Tokenizers.Tokenizer) {
        self.upstream = upstream
    }

    func encode(text: String, addSpecialTokens: Bool) -> [Int] {
        upstream.encode(text: text, addSpecialTokens: addSpecialTokens)
    }

    func decode(tokenIds: [Int], skipSpecialTokens: Bool) -> String {
        upstream.decode(tokens: tokenIds, skipSpecialTokens: skipSpecialTokens)
    }

    func convertTokenToId(_ token: String) -> Int? {
        upstream.convertTokenToId(token)
    }

    func convertIdToToken(_ id: Int) -> String? {
        upstream.convertIdToToken(id)
    }

    var bosToken: String? { upstream.bosToken }
    var eosToken: String? { upstream.eosToken }
    var unknownToken: String? { upstream.unknownToken }

    func applyChatTemplate(
        messages: [[String: any Sendable]],
        tools: [[String: any Sendable]]?,
        additionalContext: [String: any Sendable]?
    ) throws -> [Int] {
        do {
            return try upstream.applyChatTemplate(
                messages: messages, tools: tools, additionalContext: additionalContext)
        } catch Tokenizers.TokenizerError.missingChatTemplate {
            throw MLXLMCommon.TokenizerError.missingChatTemplate
        } catch {
            throw error
        }
    }
}

private struct TransformersLoader: TokenizerLoader {
    public init() {}

    public func load(from directory: URL) async throws -> any MLXLMCommon.Tokenizer {
        let upstream = try await AutoTokenizer.from(modelFolder: directory)
        return TokenizerBridge(upstream)
    }
}
