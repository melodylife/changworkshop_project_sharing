import Foundation
import Combine
import MLX
import MLXAudioCore
import MLXAudioTTS
import MLXLMCommon
import AVFoundation

@MainActor
class TTSViewModel: ObservableObject {
    @Published var text: String = "Hello from MLX Audio Swift! This is high performance, on-device audio generation running natively on Apple Silicon."
    @Published var isDownloading = false
    @Published var isGenerating = false
    @Published var isPlaying = false
    @Published var statusMessage: String = "Ready"
    @Published var generatedAudioURL: URL? = nil
    @Published var isStreamingEnabled = false
    @Published var generatedTokenCount = 0
    @Published var timeToFirstPlay: Double? = nil
    @Published var totalGenerationTime: Double? = nil
    @Published var generationSpeed: Double? = nil
    @Published var audioDuration: Double? = nil
    
    private var model: SopranoModel?
    private var audioPlayer: AVAudioPlayer?
    private var timer: Timer?
    private var generationStartTime: Double = 0
    
    func loadModel() async {
        guard model == nil else { return }
        isDownloading = true
        statusMessage = "Loading Soprano model..."
        do {
            var modelURL: URL? = nil
            
            // Check if folder exists (nested reference or bundle)
            if let nestedURL = Bundle.main.url(forResource: "Soprano-80M-bf16", withExtension: "bundle") {
                modelURL = nestedURL
                statusMessage = "Loading bundled Soprano model (80M)..."
            } else if let nestedURL = Bundle.main.url(forResource: "Soprano-80M-bf16", withExtension: nil) {
                modelURL = nestedURL
                statusMessage = "Loading bundled Soprano model (80M)..."
            }
            
            if let url = modelURL {
                model = try await SopranoModel.fromModelDirectory(url, repo: "mlx-community/Soprano-80M-bf16")
                statusMessage = "Bundled model loaded successfully!"
            } else {
                statusMessage = "Downloading and loading Soprano model (80M) from HF..."
                model = try await SopranoModel.fromPretrained("mlx-community/Soprano-80M-bf16")
                statusMessage = "Model downloaded and loaded successfully!"
            }
        } catch {
            statusMessage = "Error loading model: \(error.localizedDescription)"
            print("TTS Model Load Error: \(error)")
        }
        isDownloading = false
    }
    
    func generate() async {
        if model == nil {
            await loadModel()
        }
        
        guard let model = model else { return }
        
        isGenerating = true
        generatedAudioURL = nil
        generatedTokenCount = 0
        timeToFirstPlay = nil
        totalGenerationTime = nil
        generationSpeed = nil
        audioDuration = nil
        generationStartTime = CFAbsoluteTimeGetCurrent()
        statusMessage = "Generating speech..."
        
        do {
            let parameters = GenerateParameters(
                maxTokens: 400,
                temperature: 0.7,
                topP: 0.95
            )
            
            let textToGenerate = text
            let modelRef = model
            var finalAudio: MLXArray?
            
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
                throw NSError(domain: "TTS", code: 500, userInfo: [NSLocalizedDescriptionKey: "Failed to generate audio"])
            }
            
            // Save output audio to a temporary file
            let tempDir = FileManager.default.temporaryDirectory
            let outputURL = tempDir.appendingPathComponent("tts_output.wav")
            
            // Remove old file if exists
            if FileManager.default.fileExists(atPath: outputURL.path) {
                try? FileManager.default.removeItem(at: outputURL)
            }
            
            let samples = audio.asArray(Float.self)
            try AudioUtils.writeWavFile(samples: samples, sampleRate: Double(model.sampleRate), fileURL: outputURL)
            self.generatedAudioURL = outputURL
            self.audioDuration = Double(samples.count) / Double(model.sampleRate)
            statusMessage = "Speech generated successfully!"
            
            if !isStreamingEnabled {
                totalGenerationTime = CFAbsoluteTimeGetCurrent() - generationStartTime
            }
            
            // Autoplay the generated sound automatically!
            playAudio()
        } catch {
            statusMessage = "Error generating speech: \(error.localizedDescription)"
            print("TTS Generation Error: \(error)")
        }
        isGenerating = false
    }
    
    func playAudio() {
        guard let url = generatedAudioURL else { return }
        
        // Configure AVAudioSession for playback
        let session = AVAudioSession.sharedInstance()
        do {
            try session.setCategory(.playback, mode: .default, options: [])
            try session.setActive(true)
            
            audioPlayer = try AVAudioPlayer(contentsOf: url)
            audioPlayer?.prepareToPlay()
            audioPlayer?.play()
            isPlaying = true
            statusMessage = "Playing generated audio..."
            
            if isStreamingEnabled && timeToFirstPlay == nil && isGenerating && generationStartTime > 0 {
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
                        self.statusMessage = "Playback finished"
                        self.timer?.invalidate()
                        self.timer = nil
                    }
                }
            }
        } catch {
            statusMessage = "Playback error: \(error.localizedDescription)"
            print("AVAudioPlayer Error: \(error)")
        }
    }
    
    func stopAudio() {
        audioPlayer?.stop()
        isPlaying = false
        statusMessage = "Playback stopped"
        timer?.invalidate()
        timer = nil
    }
}
