---
license: mit
language:
- en
- zh
pipeline_tag: automatic-speech-recognition
library_name: mlx-audio
tags:
- mlx
- speech-to-text
- speech-to-speech
- speech
- speech generation
- stt
---

# mlx-community/GLM-ASR-Nano-2512-4bit
This model was converted to MLX format from [`zai-org/GLM-ASR-Nano-2512`](https://huggingface.co/zai-org/GLM-ASR-Nano-2512) using mlx-audio version **0.2.9**.
Refer to the [original model card](https://huggingface.co/zai-org/GLM-ASR-Nano-2512) for more details on the model.

## Use with mlx-audio

```bash
pip install -U mlx-audio
```

### CLI Example:
```bash
    python -m mlx_audio.stt.generate --model mlx-community/GLM-ASR-Nano-2512-4bit --audio "audio.wav"
```
### Python Example:
```python
    from mlx_audio.stt.utils import load_model
    from mlx_audio.stt.generate import generate_transcription
    model = load_model("mlx-community/GLM-ASR-Nano-2512-4bit")
    transcription = generate_transcription(
        model=model,
        audio_path="path_to_audio.wav",
        output_path="path_to_output.txt",
        format="txt",
        verbose=True,
    )
    print(transcription.text)
```
