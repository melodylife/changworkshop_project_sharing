---
library_name: mlx-audio
license: apache-2.0
pipeline_tag: text-to-speech
tags:
- mlx
- text-to-speech
- speech
- speech generation
- voice cloning
- tts
---

# mlx-community/Soprano-80M-bf16
This model was converted to MLX format from [`ekwek/Soprano-80M`](https://huggingface.co/ekwek/Soprano-80M) using mlx-audio version **0.2.10**.
Refer to the [original model card](https://huggingface.co/ekwek/Soprano-80M) for more details on the model.

## Use with mlx-audio

```bash
pip install -U mlx-audio
```

### CLI Example:
```bash
    python -m mlx_audio.tts.generate --model mlx-community/Soprano-80M-bf16 --text "Hello, this is a test."
```
### Python Example:
```python
    from mlx_audio.tts.utils import load_model
    from mlx_audio.tts.generate import generate_audio
    model = load_model("mlx-community/Soprano-80M-bf16")
    generate_audio(
        model=model, text="Hello, this is a test.",
        file_prefix="test_audio",
    )

```
