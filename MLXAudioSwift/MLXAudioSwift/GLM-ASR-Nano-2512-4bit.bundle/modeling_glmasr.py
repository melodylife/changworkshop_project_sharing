from typing import Optional

import torch
from torch import Tensor, nn
from transformers import LlamaForCausalLM
from transformers.modeling_outputs import CausalLMOutputWithPast

from .configuration_glmasr import GlmasrConfig
from .modeling_audio import WhisperSpecialEncoder


class AudioMLPAdapter(nn.Module):
    def __init__(self, config: GlmasrConfig):
        super().__init__()
        whisper_config = config.whisper_config
        self.merge_factor = config.merge_factor
        self.whisper = WhisperSpecialEncoder(
            whisper_config,
            use_rope=config.use_rope,
        )
        self.whisper.layer_norm = nn.Identity()
        self.layer_norm = nn.LayerNorm(whisper_config.hidden_size)
        act = {
            "gelu": nn.GELU(),
            "relu": nn.ReLU(),
            "selu": nn.SELU(),
        }[config.mlp_adapter_act]
        hidden = whisper_config.hidden_size * self.merge_factor
        output_dim = config.lm_config.hidden_size
        self.adapting = nn.Sequential(
            nn.Linear(hidden, output_dim * 2),
            act,
            nn.Linear(output_dim * 2, output_dim),
        )
        self.audio_bos_eos_token = nn.Embedding(2, output_dim)

    def forward(self, audios: Tensor) -> tuple[Tensor, Tensor, Tensor]:
        bsz = audios.size(0)
        encoded = self.whisper(audios)[0]
        encoded = self.layer_norm(encoded)
        encoded = encoded.reshape(bsz, -1, encoded.size(-1) * self.merge_factor)
        adapted = self.adapting(encoded)
        boa = self.audio_bos_eos_token.weight[0][None, :]
        eoa = self.audio_bos_eos_token.weight[1][None, :]
        return adapted, boa, eoa


class GlmasrModel(LlamaForCausalLM):
    config_class = GlmasrConfig

    def __init__(self, config: GlmasrConfig):
        super().__init__(config.lm_config)
        self.audio_encoder = AudioMLPAdapter(config)
        self.all_config = config

    def forward(
        self,
        input_ids: Optional[torch.LongTensor] = None,
        audios: Optional[Tensor] = None,
        audio_offsets: Optional[list[list[int]]] = None,
        audio_length: Optional[list[list[int]]] = None,
        attention_mask: Optional[Tensor] = None,
        position_ids: Optional[Tensor] = None,
        past_key_values: Optional[tuple] = None,
        use_cache: Optional[bool] = None,
        **kwargs,
    ) -> CausalLMOutputWithPast:
        tokens = input_ids
        vocab_size = self.config.vocab_size
        tokens = torch.clamp(tokens, 0, vocab_size - 1)
        language_embs = self.model.embed_tokens(tokens)

        have_audio = audios is not None and (
            kwargs.get("past_key_values") is None or len(kwargs["past_key_values"]) == 0
        )
        if have_audio:
            if audio_length is None:
                raise ValueError("audio_length is required when audio_offsets are provided")
            audio_embs, boa, eoa = self.audio_encoder(audios)
            index = 0
            for batch, (offsets, lengths) in enumerate(zip(audio_offsets, audio_length)):
                for offset, length in zip(offsets, lengths):
                    language_embs[batch, offset : offset + length] = audio_embs[index, :length]
                    language_embs[batch, offset - 1] = boa
                    language_embs[batch, offset + length] = eoa
                    index += 1

        kwargs.pop("inputs_embeds", None)
        kwargs.pop("is_first_forward", None)

        outputs = self.model(
            inputs_embeds=language_embs,
            attention_mask=attention_mask,
            position_ids=position_ids,
            past_key_values=past_key_values,
            use_cache=use_cache,
            **kwargs,
        )
        logits = self.lm_head(outputs[0])
        return CausalLMOutputWithPast(
            loss=None,
            logits=logits,
            past_key_values=outputs.past_key_values,
            hidden_states=outputs.hidden_states,
            attentions=outputs.attentions,
        )

    def _update_model_kwargs_for_generation(self, *args, **kwargs):
        model_kwargs = super()._update_model_kwargs_for_generation(*args, **kwargs)
        model_kwargs["is_first_forward"] = False
        position_ids = model_kwargs.get("position_ids")
        if position_ids is not None:
            next_pos = position_ids[..., -1:].clone() + 1
            model_kwargs["position_ids"] = torch.cat([position_ids, next_pos], dim=-1)
        return model_kwargs

    def prepare_inputs_for_generation(
        self,
        *args,
        past_key_values: Optional[tuple] = None,
        attention_mask: Optional[Tensor] = None,
        position_ids: Optional[Tensor] = None,
        use_cache: Optional[bool] = None,
        is_first_forward: bool = True,
        **kwargs,
    ):
        prepared = super().prepare_inputs_for_generation(
            *args,
            past_key_values=past_key_values,
            attention_mask=attention_mask,
            position_ids=position_ids,
            use_cache=use_cache,
            is_first_forward=is_first_forward,
            **kwargs,
        )
        for key, value in kwargs.items():
            if key not in prepared and key.startswith("audio"):
                prepared[key] = value
        if is_first_forward and past_key_values is not None and len(past_key_values) > 0:
            cached_len = past_key_values[0][0].shape[2]
            prepared["input_ids"] = prepared["input_ids"][:, cached_len:]
            if "position_ids" in prepared:
                prepared["position_ids"] = prepared["position_ids"][:, cached_len:]
        if not is_first_forward:
            prepared["audios"] = None
        return prepared


__all__ = ["GlmasrModel"]
