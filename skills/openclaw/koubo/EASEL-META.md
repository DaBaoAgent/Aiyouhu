# Easel SKILL 元数据

| 字段 | 值 |
|------|-----|
| **SKILL 名称** | koubo |
| **所属层** | produce |
| **来源类型** | 自研 |
| **原始来源** | Easel 自研；封装 `skills/shared/scripts/voice_clone.py`（云 TTS）、`audio_mix.py`（闪避混音）与 ffmpeg（apad/concat/ass/tpad），固定资产「claire 音色 / 1.4 语速 / 句间停顿 / 防吞字补尾 / 去标点字幕 / BGM 自动匹配去头静音 / 原片不压缩」约定 |
| **参考项目** | SiliconFlow 硅基流动（OpenAI 兼容 /audio/speech 托管 CosyVoice2）— https://docs.siliconflow.cn ；FFmpeg sidechaincompress / silenceremove / ass / tpad — https://ffmpeg.org |
| **许可** | 待核实（CosyVoice2: Apache-2.0；FFmpeg: LGPL/GPL；TTS 服务按云厂商条款） |

> 整理时间: 2026-10-02
> 用途: 来源溯源与致谢
> 缘起: 为「爱优护电动轮椅软广号」国庆热点二创固化配音成片参数；原名 voiceover-bgm-pack，按用户要求改名 koubo 并置顶
