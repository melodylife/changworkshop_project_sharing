import os
import base64
import json
import gc
import wave
import io
import tempfile
import numpy as np
from typing import Optional, List
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import mlx.core as mx
import mlx_vlm
from mlx_vlm import load as load_vlm, stream_generate, apply_chat_template
from mlx_audio.tts.generate import load_model as load_tts

app = FastAPI(title="MLX Multimodal Demo Backend")

# Model Manager for loading, caching, and releasing MLX models safely
class ModelManager:
    def __init__(self):
        self.vlm_model_id = None
        self.vlm_model = None
        self.vlm_processor = None
        
        self.tts_model_id = None
        self.tts_model = None

    def get_vlm(self, model_id: str):
        if self.vlm_model_id != model_id:
            print(f"Switching VLM model from {self.vlm_model_id} to {model_id}")
            self.unload_vlm()
            # Reset active TTS model to free memory if memory is low
            self.unload_tts()
            self.vlm_model, self.vlm_processor = load_vlm(model_id)
            self.vlm_model_id = model_id
        return self.vlm_model, self.vlm_processor

    def get_tts(self, model_id: str):
        if self.tts_model_id != model_id:
            print(f"Switching TTS model from {self.tts_model_id} to {model_id}")
            self.unload_tts()
            # Reset active VLM model to free memory if memory is low
            self.unload_vlm()
            self.tts_model = load_tts(model_id)
            self.tts_model_id = model_id
        return self.tts_model

    def unload_vlm(self):
        self.vlm_model = None
        self.vlm_processor = None
        self.vlm_model_id = None
        gc.collect()
        mx.clear_cache()
        print("VLM model unloaded.")

    def unload_tts(self):
        self.tts_model = None
        self.tts_model_id = None
        gc.collect()
        mx.clear_cache()
        print("TTS model unloaded.")

manager = ModelManager()

# Helper function to convert float32 array to WAV bytes
def float32_to_wav_bytes(float32_array: np.ndarray, sample_rate: int) -> bytes:
    # Scale to int16 PCM bounds
    int16_array = (np.clip(float32_array, -1.0, 1.0) * 32767).astype(np.int16)
    wav_io = io.BytesIO()
    with wave.open(wav_io, "wb") as wav_file:
        wav_file.setnchannels(1)  # Mono
        wav_file.setsampwidth(2)   # 2 bytes per sample (16-bit)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(int16_array.tobytes())
    return wav_io.getvalue()

# Preconfigured models configuration
CONFIGURED_MODELS = {
    "vlm": [
        {
            "id": "mlx-community/Qwen2-VL-2B-Instruct-4bit",
            "name": "Qwen2-VL 2B (4-bit)",
            "description": "Efficient and accurate vision-language model, perfect for general image description."
        }
    ],
    "tts": [
        {
            "id": "mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-4bit",
            "name": "Qwen3-TTS 0.6B CustomVoice (4-bit)",
            "description": "High-quality, customizable text-to-speech model supporting multiple speakers.",
            "voices": ["serena", "vivian", "uncle_fu", "ryan", "aiden", "ono_anna", "sohee", "eric", "dylan"]
        },
        {
            "id": "mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit",
            "name": "Qwen3-TTS 0.6B CustomVoice (8-bit)",
            "description": "8-bit quantized version of Qwen3-TTS, offering a balance of quality and latency.",
            "voices": ["serena", "vivian", "uncle_fu", "ryan", "aiden", "ono_anna", "sohee", "eric", "dylan"]
        },
        {
            "id": "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit",
            "name": "Qwen3-TTS 1.7B Base (8-bit)",
            "description": "Larger base model of Qwen3-TTS, offering premium prosody.",
            "voices": ["serena", "vivian", "uncle_fu", "ryan", "aiden", "ono_anna", "sohee", "eric", "dylan"]
        },
        {
            "id": "prince-canuma/Kokoro-82M",
            "name": "Kokoro 82M",
            "description": "Ultralight, extremely natural TTS model supporting English and multi-accent voices.",
            "voices": [
                "af_heart", "af_bella", "af_nicole", "af_sarah", "af_alloy", "af_nova", "af_sky",
                "am_adam", "am_michael", "am_eric", "am_liam", "am_echo",
                "bf_emma", "bf_isabella", "bf_alice", "bf_lily",
                "bm_george", "bm_lewis", "bm_daniel"
            ]
        }
    ]
}

# Request schema for TTS
class TTSRequest(BaseModel):
    model_id: str
    text: str
    voice: str
    speed: float = 1.0
    lang_code: str = "en"

@app.get("/api/models")
def get_models():
    return CONFIGURED_MODELS

# Generator for streaming VLM response
async def vlm_stream_generator(image_path: str, model_id: str, prompt_text: str):
    try:
        model, processor = manager.get_vlm(model_id)
        
        # Build prompt using chat template
        messages = [{'role': 'user', 'content': [{'type': 'image'}, {'type': 'text', 'text': prompt_text}]}]
        prompt = apply_chat_template(processor, model.config, messages, num_images=1)
        
        for chunk in stream_generate(model, processor, prompt, image=[image_path]):
            data = {
                "text": chunk.text,
                "metrics": {
                    "generation_tps": round(getattr(chunk, "generation_tps", 0.0), 2),
                    "prompt_tps": round(getattr(chunk, "prompt_tps", 0.0), 2),
                    "peak_memory": round(getattr(chunk, "peak_memory", 0.0), 3),
                    "prompt_tokens": getattr(chunk, "prompt_tokens", 0),
                    "generation_tokens": getattr(chunk, "generation_tokens", 0),
                }
            }
            yield f"data: {json.dumps(data)}\n\n"
    except Exception as e:
        import traceback
        traceback.print_exc()
        yield f"data: {json.dumps({'error': str(e)})}\n\n"
    finally:
        # Safely clean up the temp image file
        if os.path.exists(image_path):
            try:
                os.remove(image_path)
            except OSError:
                pass

@app.post("/api/vlm/generate")
async def vlm_generate(
    image: UploadFile = File(...),
    model_id: str = Form(...),
    prompt: str = Form("Describe this image in detail.")
):
    # Save the file to a temporary file
    temp_dir = tempfile.gettempdir()
    suffix = os.path.splitext(image.filename)[1] or ".png"
    fd, temp_file_path = tempfile.mkstemp(suffix=suffix, dir=temp_dir)
    os.close(fd)
    
    with open(temp_file_path, "wb") as buffer:
        buffer.write(await image.read())
        
    return StreamingResponse(
        vlm_stream_generator(temp_file_path, model_id, prompt),
        media_type="text/event-stream"
    )

@app.post("/api/tts/generate")
async def tts_generate(request: TTSRequest):
    try:
        model = manager.get_tts(request.model_id)
        
        # Map language codes appropriately
        actual_lang = request.lang_code
        if "kokoro" in request.model_id.lower():
            if actual_lang == "zh":
                actual_lang = "z"
            else:
                actual_lang = "a"

        # We explicitly track metrics as we iterate through generator results
        results = model.generate(
            text=request.text,
            voice=request.voice,
            speed=request.speed,
            lang_code=actual_lang,
            stream=False
        )
        
        all_audio = []
        sample_rate = 24000
        total_processing_time = 0.0
        peak_memory = 0.0
        duration_str = "0.0"
        
        for result in results:
            all_audio.append(np.array(result.audio))
            sample_rate = result.sample_rate
            total_processing_time += result.processing_time_seconds
            peak_memory = max(peak_memory, result.peak_memory_usage)
            duration_str = result.audio_duration
            
        if not all_audio:
            raise HTTPException(status_code=500, detail="No audio was generated")
            
        full_audio = np.concatenate(all_audio)
        wav_bytes = float32_to_wav_bytes(full_audio, sample_rate)
        wav_base64 = base64.b64encode(wav_bytes).decode('utf-8')
        
        # Calculate real-time factor
        duration_seconds = len(full_audio) / sample_rate
        rtf = total_processing_time / duration_seconds if duration_seconds > 0 else 0.0
        
        metrics = {
            "duration": duration_str,
            "processing_time": round(total_processing_time, 2),
            "real_time_factor": round(rtf, 2),
            "peak_memory": round(peak_memory, 3),
            "sample_rate": sample_rate,
            "samples": len(full_audio)
        }
        
        return {
            "audio": wav_base64,
            "metrics": metrics
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

# Generator for streaming TTS chunks
async def tts_stream_generator(request: TTSRequest):
    try:
        model = manager.get_tts(request.model_id)
        
        # Map language codes appropriately
        actual_lang = request.lang_code
        if "kokoro" in request.model_id.lower():
            if actual_lang == "zh":
                actual_lang = "z"
            else:
                actual_lang = "a"

        # Kokoro doesn't support token-by-token streaming, but it streams segment-by-segment automatically
        results = model.generate(
            text=request.text,
            voice=request.voice,
            speed=request.speed,
            lang_code=actual_lang,
            stream=True
        )
        
        for result in results:
            audio_np = np.array(result.audio)
            audio_bytes = audio_np.tobytes()
            audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')
            
            is_final = getattr(result, "is_final_chunk", False) or not getattr(result, "is_streaming_chunk", True)
            
            data = {
                "audio": audio_base64,
                "sample_rate": result.sample_rate,
                "is_final": is_final,
                "metrics": {
                    "duration": result.audio_duration,
                    "processing_time": round(result.processing_time_seconds, 2),
                    "real_time_factor": round(result.real_time_factor, 2),
                    "peak_memory": round(result.peak_memory_usage, 3),
                    "token_count": result.token_count,
                    "samples": len(audio_np)
                }
            }
            yield f"data: {json.dumps(data)}\n\n"
    except Exception as e:
        import traceback
        traceback.print_exc()
        yield f"data: {json.dumps({'error': str(e)})}\n\n"

@app.post("/api/tts/stream")
async def tts_stream(request: TTSRequest):
    return StreamingResponse(
        tts_stream_generator(request),
        media_type="text/event-stream"
    )

# Serve static folder
os.makedirs("static", exist_ok=True)
app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
