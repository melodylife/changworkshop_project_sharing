// State management
let appModels = null;
let activeVlmModel = null;
let activeTtsModel = null;

// Audio player state
let audioContext = null;
let nextStartTime = 0;
let playingSourceNodes = [];
let isAudioPlaying = false;
let audioPlayTimeout = null;

// DOM Elements
const vlmModelSelect = document.getElementById("vlm-model-select");
const ttsModelSelect = document.getElementById("tts-model-select");
const ttsVoiceSelect = document.getElementById("tts-voice-select");
const speedSlider = document.getElementById("tts-speed-slider");
const speedVal = document.getElementById("speed-val");
const streamToggle = document.getElementById("tts-stream-toggle");
const ttsText = document.getElementById("tts-input-text");
const ttsModeBadge = document.getElementById("tts-mode-badge");

const vlmBtn = document.getElementById("vlm-btn");
const vlmSpinner = document.getElementById("vlm-spinner");
const narrateBtn = document.getElementById("narrate-btn");
const narrateSpinner = document.getElementById("narrate-spinner");
const vlmOutput = document.getElementById("vlm-output-box");

const ttsBtn = document.getElementById("tts-btn");
const ttsSpinner = document.getElementById("tts-spinner");
const playPauseBtn = document.getElementById("play-pause-btn");
const playIcon = playPauseBtn.querySelector(".play-icon");
const pauseIcon = playPauseBtn.querySelector(".pause-icon");
const waveformVis = document.getElementById("waveform-vis");
const audioElement = document.getElementById("tts-audio-element");

const uploadZone = document.getElementById("upload-zone");
const imageInput = document.getElementById("image-input");
const uploadPrompt = document.getElementById("upload-prompt");
const uploadPreview = document.getElementById("upload-preview");
const previewImg = document.getElementById("preview-img");
const removeImgBtn = document.getElementById("remove-img-btn");
const vlmPromptInput = document.getElementById("vlm-prompt");
const langSelect = document.getElementById("lang-select");

// Status Badges
const vlmActiveBadge = document.getElementById("vlm-active-model");
const ttsActiveBadge = document.getElementById("tts-active-model");
const vlmStatusDot = document.getElementById("vlm-status-dot");
const ttsStatusDot = document.getElementById("tts-status-dot");

// Metrics elements
const vlmMetricPromptSpeed = document.getElementById("vlm-metric-prompt-speed");
const vlmMetricGenSpeed = document.getElementById("vlm-metric-gen-speed");
const vlmMetricTokens = document.getElementById("vlm-metric-tokens");
const vlmMetricMemory = document.getElementById("vlm-metric-memory");

const ttsMetricLatency = document.getElementById("tts-metric-latency");
const ttsMetricRtf = document.getElementById("tts-metric-rtf");
const ttsMetricSpecs = document.getElementById("tts-metric-specs");
const ttsMetricSpecsUnit = document.getElementById("tts-metric-specs-unit");
const ttsMetricMemory = document.getElementById("tts-metric-memory");

// Initialize application
async function init() {
    try {
        setupEventListeners();
        createWaveformIdleBars();
        await fetchModels();
    } catch (e) {
        console.error("Initialization failed", e);
        alert("Could not load backend configurations. Please ensure the FastAPI server is running.");
    }
}

// Event Listeners setup
function setupEventListeners() {
    // Dropdowns & sliders
    speedSlider.addEventListener("input", (e) => {
        speedVal.textContent = parseFloat(e.target.value).toFixed(1) + "x";
    });
    
    streamToggle.addEventListener("change", (e) => {
        if (e.target.checked) {
            ttsModeBadge.textContent = "stream mode";
            ttsModeBadge.className = "output-type-badge audio-badge";
        } else {
            ttsModeBadge.textContent = "standard mode";
            ttsModeBadge.className = "output-type-badge text-badge"; // teal colored
        }
    });

    ttsModelSelect.addEventListener("change", (e) => {
        updateVoiceList(e.target.value);
    });

    langSelect.addEventListener("change", handleLanguageChange);

    // Image Upload Zone triggers
    uploadZone.addEventListener("click", (e) => {
        if (e.target !== removeImgBtn) {
            imageInput.click();
        }
    });

    imageInput.addEventListener("change", (e) => {
        if (e.target.files && e.target.files[0]) {
            handleImageFile(e.target.files[0]);
        }
    });

    // Drag & Drop
    uploadZone.addEventListener("dragover", (e) => {
        e.preventDefault();
        uploadZone.classList.add("dragover");
    });

    uploadZone.addEventListener("dragleave", () => {
        uploadZone.classList.remove("dragover");
    });

    uploadZone.addEventListener("drop", (e) => {
        e.preventDefault();
        uploadZone.classList.remove("dragover");
        if (e.dataTransfer.files && e.dataTransfer.files[0]) {
            handleImageFile(e.dataTransfer.files[0]);
        }
    });

    removeImgBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        clearUploadedImage();
    });

    // Action button events
    vlmBtn.addEventListener("click", () => runVlmAnalysis(false));
    narrateBtn.addEventListener("click", runNarrateWorkflow);
    ttsBtn.addEventListener("click", runTtsSynthesis);

    // Audio Play/Pause trigger (Standard Mode or streamed pause)
    playPauseBtn.addEventListener("click", toggleAudioPlayback);

    // Standard audio tag event listeners
    audioElement.addEventListener("play", () => {
        setAudioPlayingState(true);
    });
    audioElement.addEventListener("ended", () => {
        setAudioPlayingState(false);
    });
    audioElement.addEventListener("pause", () => {
        setAudioPlayingState(false);
    });
}

// Fetch available models from backend
async function fetchModels() {
    const res = await fetch("/api/models");
    if (!res.ok) throw new Error("HTTP error " + res.status);
    appModels = await res.json();

    // Populate VLM select dropdown
    vlmModelSelect.innerHTML = "";
    appModels.vlm.forEach(model => {
        const opt = document.createElement("option");
        opt.value = model.id;
        opt.textContent = model.name;
        opt.title = model.description;
        vlmModelSelect.appendChild(opt);
    });

    // Populate TTS select dropdown
    ttsModelSelect.innerHTML = "";
    appModels.tts.forEach(model => {
        const opt = document.createElement("option");
        opt.value = model.id;
        opt.textContent = model.name;
        opt.title = model.description;
        ttsModelSelect.appendChild(opt);
    });

    // Initialize voices list based on default selected model
    if (appModels.tts.length > 0) {
        updateVoiceList(appModels.tts[0].id);
    }
}

// Populate speaker voices dynamically, filtering Kokoro voices by selected language
function updateVoiceList(modelId) {
    const selectedModel = appModels.tts.find(m => m.id === modelId);
    ttsVoiceSelect.innerHTML = "";
    if (!selectedModel || !selectedModel.voices) return;

    const lang = langSelect.value;
    let filteredVoices = selectedModel.voices;

    // Kokoro model has strict language-specific voice databases
    if (modelId.includes("Kokoro")) {
        if (lang === "zh") {
            // Show only Chinese voices
            filteredVoices = selectedModel.voices.filter(v => v.startsWith("zf_") || v.startsWith("zm_"));
        } else {
            // Show only English voices
            filteredVoices = selectedModel.voices.filter(v => !v.startsWith("zf_") && !v.startsWith("zm_"));
        }
    }

    filteredVoices.forEach(voice => {
        const opt = document.createElement("option");
        opt.value = voice;
        opt.textContent = voice.replace("_", " ");
        ttsVoiceSelect.appendChild(opt);
    });
}

// Handle global language change
function handleLanguageChange() {
    const lang = langSelect.value;
    
    // 1. Update VLM prompt default
    if (lang === "zh") {
        vlmPromptInput.value = "请详细描述这张图片。";
        ttsText.value = "欢迎来到苹果芯片多模态实验室。本语音是由 MLX 框架在设备端实时合成的。";
    } else {
        vlmPromptInput.value = "Describe this image in detail.";
        ttsText.value = "Welcome to the Apple Silicon Multimodal Laboratory. This voice is synthesized on-device in real-time using the MLX framework.";
    }

    // 2. Re-populate TTS voices based on current model and new language
    updateVoiceList(ttsModelSelect.value);
}

// Handle uploaded image file
function handleImageFile(file) {
    const reader = new FileReader();
    reader.onload = (e) => {
        previewImg.src = e.target.result;
        uploadPrompt.style.display = "none";
        uploadPreview.style.display = "flex";
        vlmBtn.disabled = false;
        narrateBtn.disabled = false;
    };
    reader.readAsDataURL(file);
}

// Clear uploaded image state
function clearUploadedImage() {
    imageInput.value = "";
    previewImg.src = "";
    uploadPreview.style.display = "none";
    uploadPrompt.style.display = "flex";
    vlmBtn.disabled = true;
    narrateBtn.disabled = true;
}

// Waveform Idle display
function createWaveformIdleBars() {
    waveformVis.innerHTML = "";
    for (let i = 0; i < 40; i++) {
        const bar = document.createElement("div");
        bar.className = "waveform-bar";
        // randomize idle height a tiny bit
        bar.style.height = (4 + Math.random() * 6) + "px";
        waveformVis.appendChild(bar);
    }
}

// Start visualizer animation
function animateWaveform(isActive) {
    const bars = waveformVis.querySelectorAll(".waveform-bar");
    bars.forEach(bar => {
        if (isActive) {
            bar.classList.add("active");
            // randomize animation delay so they bounce staggered
            bar.style.animationDelay = (Math.random() * 0.8) + "s";
        } else {
            bar.classList.remove("active");
            bar.style.height = (4 + Math.random() * 6) + "px";
        }
    });
}

// VLM inference triggers
// VLM inference triggers
async function runVlmAnalysis(isNarrate = false) {
    const file = imageInput.files[0];
    if (!file) return "";

    const modelId = vlmModelSelect.value;
    const promptText = vlmPromptInput.value;

    // Reset UI
    vlmBtn.disabled = true;
    narrateBtn.disabled = true;
    ttsBtn.disabled = true;
    
    const activeSpinner = isNarrate ? narrateSpinner : vlmSpinner;
    activeSpinner.style.display = "inline-block";
    
    vlmOutput.innerHTML = '<span class="loading-text">Ingesting image and loading model...</span>';
    setModuleStatus("vlm", "loading", modelId);

    const formData = new FormData();
    formData.append("image", file);
    formData.append("model_id", modelId);
    formData.append("prompt", promptText);

    let accumulatedText = "";

    try {
        const response = await fetch("/api/vlm/generate", {
            method: "POST",
            body: formData
        });

        if (!response.ok) throw new Error("HTTP error " + response.status);

        vlmOutput.innerHTML = "";
        setModuleStatus("vlm", "active", modelId);

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop();

            for (const line of lines) {
                if (line.startsWith("data: ")) {
                    const jsonStr = line.slice(6).trim();
                    if (!jsonStr) continue;

                    const data = JSON.parse(jsonStr);
                    if (data.error) {
                        vlmOutput.innerHTML = `<span style="color:#ef4444;">Error: ${data.error}</span>`;
                        break;
                    }

                    if (data.text) {
                        accumulatedText += data.text;
                        vlmOutput.appendChild(document.createTextNode(data.text));
                        vlmOutput.scrollTop = vlmOutput.scrollHeight;
                    }

                    if (data.metrics) {
                        vlmMetricPromptSpeed.textContent = data.metrics.prompt_tps || "-";
                        vlmMetricGenSpeed.textContent = data.metrics.generation_tps || "-";
                        vlmMetricTokens.textContent = `${data.metrics.prompt_tokens}p / ${data.metrics.generation_tokens}g`;
                        vlmMetricMemory.textContent = data.metrics.peak_memory || "-";
                    }
                }
            }
        }
        
        setModuleStatus("vlm", "idle", modelId);

    } catch (e) {
        console.error(e);
        vlmOutput.innerHTML = `<span style="color:#ef4444;">Connection failed: ${e.message}</span>`;
        setModuleStatus("vlm", "idle", "Error");
    } finally {
        vlmBtn.disabled = false;
        narrateBtn.disabled = false;
        ttsBtn.disabled = false;
        activeSpinner.style.display = "none";
    }

    return accumulatedText;
}

// Consolidated Narrate Image workflow
async function runNarrateWorkflow() {
    // Stop any playing audio
    stopStreamedAudio();
    audioElement.pause();
    audioElement.src = "";

    // 1. Run VLM analysis to get description
    const descriptionText = await runVlmAnalysis(true);
    if (!descriptionText) {
        return;
    }

    // 2. Feed the generated description text into the TTS input field
    ttsText.value = descriptionText;

    // 3. Trigger TTS generation
    await runTtsSynthesis();
}

// Convert Base64 raw float32 PCM data to Float32Array
function base64ToFloat32Array(base64) {
    const binaryString = atob(base64);
    const len = binaryString.length;
    const bytes = new Uint8Array(len);
    for (let i = 0; i < len; i++) {
        bytes[i] = binaryString.charCodeAt(i);
    }
    return new Float32Array(bytes.buffer);
}

// Toggle play/pause for standard audio or streaming audio
function toggleAudioPlayback() {
    if (streamToggle.checked) {
        // In stream mode, stopping audio clears context and queued buffers
        if (isAudioPlaying) {
            stopStreamedAudio();
        }
    } else {
        // Standard mode audio element toggle
        if (audioElement.paused) {
            audioElement.play();
        } else {
            audioElement.pause();
        }
    }
}

// Set UI active/inactive status for audio
function setAudioPlayingState(isPlaying) {
    isAudioPlaying = isPlaying;
    if (isPlaying) {
        playIcon.style.display = "none";
        pauseIcon.style.display = "inline";
        animateWaveform(true);
    } else {
        playIcon.style.display = "inline";
        pauseIcon.style.display = "none";
        animateWaveform(false);
    }
}

// Stop streamed audio nodes
function stopStreamedAudio() {
    if (audioPlayTimeout) {
        clearTimeout(audioPlayTimeout);
        audioPlayTimeout = null;
    }
    playingSourceNodes.forEach(node => {
        try { node.stop(); } catch(e) {}
    });
    playingSourceNodes = [];
    setAudioPlayingState(false);
}

// TTS Inference triggers
async function runTtsSynthesis() {
    // Stop any currently playing audio before starting new generation
    stopStreamedAudio();
    audioElement.pause();
    audioElement.src = "";

    const modelId = ttsModelSelect.value;
    const textVal = ttsText.value.trim();
    const voiceVal = ttsVoiceSelect.value;
    const speedValNum = parseFloat(speedSlider.value);
    const isStream = streamToggle.checked;

    if (!textVal) {
        alert("Please enter text to speak");
        return;
    }

    // Reset metrics
    ttsMetricLatency.textContent = "-";
    ttsMetricRtf.textContent = "-";
    ttsMetricSpecs.textContent = "-";
    ttsMetricSpecsUnit.textContent = "";
    ttsMetricMemory.textContent = "-";

    ttsBtn.disabled = true;
    ttsSpinner.style.display = "inline-block";
    playPauseBtn.disabled = true;
    waveformVis.innerHTML = '<div class="vis-idle">Generating audio...</div>';

    setModuleStatus("tts", "loading", modelId);

    const payload = {
        model_id: modelId,
        text: textVal,
        voice: voiceVal,
        speed: speedValNum,
        lang_code: langSelect.value
    };

    if (isStream) {
        // Stream mode via SSE
        try {
            // Initialize Web Audio context
            if (!audioContext) {
                audioContext = new (window.AudioContext || window.webkitAudioContext)();
            }
            if (audioContext.state === 'suspended') {
                await audioContext.resume();
            }
            
            // Queue tracking
            nextStartTime = audioContext.currentTime + 0.1; // small offset buffer
            playingSourceNodes = [];
            
            const response = await fetch("/api/tts/stream", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });

            if (!response.ok) throw new Error("HTTP response error " + response.status);

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";
            let chunkCount = 0;
            let totalLatency = 0;
            let maxMemory = 0;
            let finalSampleRate = 24000;
            let totalDuration = 0;

            waveformVis.innerHTML = "";
            // Add custom animation bars
            for (let i = 0; i < 40; i++) {
                const bar = document.createElement("div");
                bar.className = "waveform-bar";
                bar.style.height = "6px";
                waveformVis.appendChild(bar);
            }

            setModuleStatus("tts", "active", modelId);
            setAudioPlayingState(true);
            playPauseBtn.disabled = false;

            while (true) {
                const { value, done } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split("\n");
                buffer = lines.pop();

                for (const line of lines) {
                    if (line.startsWith("data: ")) {
                        const jsonStr = line.slice(6).trim();
                        if (!jsonStr) continue;

                        const data = JSON.parse(jsonStr);
                        if (data.error) {
                            alert("Backend speech generation failed: " + data.error);
                            break;
                        }

                        // Play the chunk if it contains audio
                        if (data.audio) {
                            const float32Samples = base64ToFloat32Array(data.audio);
                            const sampleRate = data.sample_rate || 24000;
                            finalSampleRate = sampleRate;
                            
                            // Queue Audio Source
                            const audioBuffer = audioContext.createBuffer(1, float32Samples.length, sampleRate);
                            audioBuffer.copyToChannel(float32Samples, 0);

                            const source = audioContext.createBufferSource();
                            source.buffer = audioBuffer;
                            source.connect(audioContext.destination);
                            
                            const currentTime = audioContext.currentTime;
                            let playTime = nextStartTime;
                            if (playTime < currentTime) {
                                playTime = currentTime;
                            }
                            
                            source.start(playTime);
                            nextStartTime = playTime + audioBuffer.duration;
                            playingSourceNodes.push(source);
                            totalDuration += audioBuffer.duration;

                            chunkCount++;
                        }

                        // Render performance metrics
                        if (data.metrics) {
                            totalLatency += data.metrics.processing_time;
                            maxMemory = Math.max(maxMemory, data.metrics.peak_memory);
                            
                            ttsMetricLatency.textContent = totalLatency.toFixed(2) + "s";
                            ttsMetricRtf.textContent = data.metrics.real_time_factor + "x";
                            ttsMetricSpecs.textContent = totalDuration.toFixed(1) + "s";
                            ttsMetricSpecsUnit.textContent = `@ ${(finalSampleRate/1000).toFixed(1)}kHz`;
                            ttsMetricMemory.textContent = maxMemory.toFixed(3);
                        }
                    }
                }
            }

            // Schedule a timeout to set playing state to false when all queued nodes are finished
            const waitTimeMs = Math.max(0, (nextStartTime - audioContext.currentTime) * 1000);
            if (audioPlayTimeout) clearTimeout(audioPlayTimeout);
            audioPlayTimeout = setTimeout(() => {
                setAudioPlayingState(false);
                playPauseBtn.disabled = true;
                createWaveformIdleBars();
            }, waitTimeMs);

            setModuleStatus("tts", "idle", modelId);

        } catch (e) {
            console.error(e);
            alert("TTS stream request failed: " + e.message);
            setAudioPlayingState(false);
            setModuleStatus("tts", "idle", "Error");
            createWaveformIdleBars();
        } finally {
            ttsBtn.disabled = false;
            ttsSpinner.style.display = "none";
        }

    } else {
        // Standard mode - complete audio file download
        try {
            const response = await fetch("/api/tts/generate", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });

            if (!response.ok) throw new Error("HTTP response error " + response.status);

            const data = await response.json();
            
            // Set standard audio source using Base64 data URI
            const binaryString = atob(data.audio);
            const len = binaryString.length;
            const bytes = new Uint8Array(len);
            for (let i = 0; i < len; i++) {
                bytes[i] = binaryString.charCodeAt(i);
            }
            const blob = new Blob([bytes], { type: "audio/wav" });
            const blobUrl = URL.createObjectURL(blob);

            audioElement.src = blobUrl;
            playPauseBtn.disabled = false;

            // Start playing standard audio element
            audioElement.play();

            // Populate dashboard metrics
            if (data.metrics) {
                ttsMetricLatency.textContent = data.metrics.processing_time + "s";
                ttsMetricRtf.textContent = data.metrics.real_time_factor + "x";
                ttsMetricSpecs.textContent = data.metrics.duration.replace("00:", ""); // remove hours if empty
                ttsMetricSpecsUnit.textContent = `@ ${(data.metrics.sample_rate/1000).toFixed(1)}kHz`;
                ttsMetricMemory.textContent = data.metrics.peak_memory;
            }

            setModuleStatus("tts", "idle", modelId);

        } catch (e) {
            console.error(e);
            alert("TTS synthesis failed: " + e.message);
            setModuleStatus("tts", "idle", "Error");
            createWaveformIdleBars();
        } finally {
            ttsBtn.disabled = false;
            ttsSpinner.style.display = "none";
        }
    }
}

// Utility to set module loading status indicators
function setModuleStatus(module, status, modelName) {
    // module is either 'vlm' or 'tts'
    const activeLabel = module === 'vlm' ? vlmActiveBadge : ttsActiveBadge;
    const dot = module === 'vlm' ? vlmStatusDot : ttsStatusDot;
    const cleanName = modelName.split("/").pop(); // print only short repo name

    activeLabel.textContent = cleanName;
    dot.className = `status-dot ${status}`;
}

// Bootstrap
window.addEventListener("DOMContentLoaded", init);
