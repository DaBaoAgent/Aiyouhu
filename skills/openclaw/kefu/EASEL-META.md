# Easel SKILL 元数据

| 字段 | 值 |
|------|-----|
| **SKILL 名称** | kefu |
| **所属层** | produce |
| **来源类型** | 自研 |
| **原始来源** | Easel 自研；编排 `ai-image-gen`（客服形象图）、`tts-voiceover`（云配音）、`autodl-h3-video`（`image_audio` 图+音频对口型）、`video_ops.py`（BGM 混音）；字幕样式逐字节复刻 `koubo`（微软雅黑 / 加粗 / 白字黑边 / 底部居中 / 去标点） |
| **参考项目** | AutoDL.Art MiniMax H3 `minimax_h3_image_audio_to_video` 工作流 — https://autodl.art ；SiliconFlow 硅基流动托管 CosyVoice2 — https://docs.siliconflow.cn ；FFmpeg `ass` 滤镜 — https://ffmpeg.org |
| **许可** | 待核实（CosyVoice2: Apache-2.0；FFmpeg: LGPL/GPL；H3 与 TTS 服务按云厂商条款） |

> 整理时间: 2026-10-03
> 用途: 来源溯源与致谢
> 缘起: 为「爱优护电动轮椅软广号」做一个「客服模样的女孩偷偷打电话、直接对口型说台词」的软广成片；
> 按用户要求封装为技能 `kefu` 并置顶（与 sanguo / koubo 同列置顶区）。
