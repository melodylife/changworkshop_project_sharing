import Foundation
import Combine
import MLX
import MLXAudioCore
import MLXAudioSTT
import AVFoundation

@MainActor
class STTViewModel: ObservableObject {
    @Published var transcription: String = ""
    @Published var isDownloading = false
    @Published var isTranscribing = false
    @Published var isRecording = false
    @Published var statusMessage: String = "Ready"
    
    private var model: GLMASRModel?
    private var audioRecorder: AVAudioRecorder?
    private var recordingURL: URL?
    
    // Check and request microphone permissions
    func checkMicrophonePermission() async -> Bool {
        let session = AVAudioSession.sharedInstance()
        switch session.recordPermission {
        case .granted:
            return true
        case .denied:
            return false
        case .undetermined:
            return await withCheckedContinuation { continuation in
                session.requestRecordPermission { granted in
                    continuation.resume(returning: granted)
                }
            }
        @unknown default:
            return false
        }
    }
    
    func loadModel() async {
        guard model == nil else { return }
        isDownloading = true
        statusMessage = "Loading GLM-ASR-Nano model..."
        do {
            var modelURL: URL? = nil
            if let nestedURL = Bundle.main.url(forResource: "GLM-ASR-Nano-2512-4bit", withExtension: "bundle") {
                modelURL = nestedURL
                statusMessage = "Loading bundled ASR model..."
            } else if let nestedURL = Bundle.main.url(forResource: "GLM-ASR-Nano-2512-4bit", withExtension: nil) {
                modelURL = nestedURL
                statusMessage = "Loading bundled ASR model..."
            }
            
            if let url = modelURL {
                model = try await GLMASRModel.fromModelDirectory(url)
                statusMessage = "Bundled ASR model loaded successfully!"
            } else {
                statusMessage = "Downloading and loading GLM-ASR-Nano model from HF..."
                model = try await GLMASRModel.fromPretrained("mlx-community/GLM-ASR-Nano-2512-4bit")
                statusMessage = "Model loaded successfully!"
            }
        } catch {
            statusMessage = "Error loading model: \(error.localizedDescription)"
            print("STT Model Load Error: \(error)")
        }
        isDownloading = false
    }
    
    func startRecording() async {
        let hasPermission = await checkMicrophonePermission()
        guard hasPermission else {
            statusMessage = "Microphone permission denied. Enable in Settings."
            return
        }
        
        let session = AVAudioSession.sharedInstance()
        do {
            try session.setCategory(.record, mode: .measurement, options: [])
            try session.setActive(true)
            
            let tempDir = FileManager.default.temporaryDirectory
            let fileURL = tempDir.appendingPathComponent("stt_input.wav")
            self.recordingURL = fileURL
            
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
            statusMessage = "Recording..."
            transcription = ""
        } catch {
            statusMessage = "Recording error: \(error.localizedDescription)"
            print("AVAudioRecorder Error: \(error)")
        }
    }
    
    func stopRecording() async {
        audioRecorder?.stop()
        isRecording = false
        statusMessage = "Recording stopped. Processing audio..."
        
        // Deactivate audio session
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        
        await transcribe()
    }
    
    func transcribe() async {
        guard let url = recordingURL else {
            statusMessage = "No recording found."
            return
        }
        
        if model == nil {
            await loadModel()
        }
        
        guard let model = model else { return }
        
        isTranscribing = true
        statusMessage = "Transcribing audio..."
        
        do {
            // Load and resample audio data to 16kHz
            let (_, audioData) = try loadAudioArray(from: url, sampleRate: 16000)
            
            let modelRef = model
            let result = try await Task.detached(priority: .userInitiated) {
                modelRef.generate(audio: audioData)
            }.value
            
            transcription = result.text
            statusMessage = "Transcription finished!"
        } catch {
            statusMessage = "Transcription error: \(error.localizedDescription)"
            print("STT Transcription Error: \(error)")
        }
        isTranscribing = false
    }
}
