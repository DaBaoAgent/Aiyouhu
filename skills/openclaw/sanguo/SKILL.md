---
name: sanguo
description: >-
  三国 IP 软广短视频（2010 版《三国》人物形象）：以诸葛亮等三国人物的口吻讲电动轮椅选购干货 / 避坑，
  角色参考图定妆、三国音色参考合成口播、H3 对口型出片，匹配三国 BGM，产出竖屏短视频。
  当用户说「用三国人物做视频」「诸葛亮 / 刘备 / 曹操… 讲…」「三国音色」「三国 BGM」「三国软广」时使用。
  与 koubo 的区别：koubo 是通用口播广告全链路；本 SKILL 在 koubo 之上叠加三国角色素材库与
  「音色参考 → 对口型」专线，角色形象、音色、BGM 全部取自固定素材目录。
layer: produce
---

# sanguo · 三国 IP 软广短视频

> 把「三国人物口吻 + 电动轮椅干货」做成竖屏短视频。角色形象、音色、BGM 都取自项目根固定素材库，
> 音色走 **H3 indextts2 音色参考**，画面走 **H3 image_audio 对口型**（或 multi_image），最后配字幕与三国 BGM。

## ⚠️ 环境铁律

先 `cd` 到 `AGENTS.md` 末尾给出的 Easel 项目根（含 `.env` 与 `skills/shared/scripts/`），再用根相对路径。
不得在 workspace 跑副本，不得用 `env` / `printenv` 推断 Key 缺失。

## 素材库（项目根相对路径）

| 类型 | 目录 | 说明 |
|------|------|------|
| 人物参考图 | `人物参考图/三国2010/` | 44 张（2010 版人物妆造）。`000-A…F` 为诸葛亮：青年 / 中年 / 老年的「全身·含轮椅」与「半身·纯人物」两版 |
| 角色音色 | `三国音色/<角色>.mp3` | 每角色一段音色样本，作 H3 `tts` 的**音色参考音频**（字段 `prompt_simple`；诸葛亮分 年轻 / 老年 / 垂暮） |
| 三国 BGM | `三国音色/三国BGM/` | `诸葛亮BGM.mp3`、`卧龙吟.mp3`、`丞相保重.mp3`、`三国恋 宿命版.mp3`、`10月2日*.mp3` |
| 产品素材 | `轻便侠218白底参考图/` 等 | 电动轮椅产品白底图，可作 multi_image 的产品参考 |

## 角色映射（可扩展；诸葛亮为软广主角色）

| 角色 | 参考图（`人物参考图/三国2010/`） | 音色（`三国音色/`） | 建议 BGM（`三国音色/三国BGM/`） |
|------|------|------|------|
| 诸葛亮·老年 | `000-F …（半身·纯人物）` 口播特写 / `000-E …（全身·含轮椅）` 带产品 | `诸葛亮-老年.mp3`（或 `诸葛亮-垂暮.mp3`） | `诸葛亮BGM.mp3` / `卧龙吟.mp3` |
| 诸葛亮·中年 | `000-D …（半身）` / `000-C …（全身·含轮椅）` | `诸葛亮-老年.mp3` | `诸葛亮BGM.mp3` |
| 诸葛亮·青年 | `000-B …（半身）` / `000-A …（全身·含轮椅）` | `诸葛亮-年轻.mp3` | `卧龙吟.mp3` |
| 刘备 | `001 刘备｜主公（2010版·于和伟）.png` | `刘备.mp3` | `卧龙吟.mp3` |
| 曹操 | `024 曹操｜魏王（2010版·陈建斌）.png` | `曹操.mp3` | `丞相保重.mp3` |
| 司马懿 | `025 司马懿｜大都督（2010版·倪大红）.png` | `司马懿.mp3` | `丞相保重.mp3` |
| 姜维 | `009 姜维｜大将军.png` | `诸葛亮-老年.mp3` | `丞相保重.mp3` |

> 其余角色音色：关羽 / 张飞 / 赵云 / 周瑜 / 孙权 / 吕布 / 貂蝉 / 大乔 / 小乔 / 董卓 / 袁绍 / 荀彧 / 张辽 / 邢道荣。
> 轮椅设定只作自然行动道具，不古装化、不给产品特写、不写卖点。

## 流程

| 环节 | 做什么 | 复用 |
|------|--------|------|
| S1 选题 | 取热点/选题（`skill-trending-topics` 等） | 发现层 |
| S2 文案 | 三国人物口吻 + 画像红线，竖屏短句（约 4 字/秒），存 `文案初稿_<name>.md` | `copywriting` |
| S3 音色参考配音 | H3 `tts`：`-a` 角色音色样本 + `--prompt` 台词 → 口播音频 | `autodl-h3-video/scripts/h3_video.py -w tts` |
| S4 画面 | **对口型**：H3 `image_audio`（角色图 + 口播音频，1–15s）；或 **画面生成**：H3 `multi_image` 两段（≤10s/段）拼接 | `autodl-h3-video/scripts/h3_video.py` + `video_ops.py concat` |
| S5 后期 | 字幕 + BGM（三国BGM 显式指定）。**字幕样式沿用 koubo**：`Microsoft YaHei`、`Fontsize=max(34,int(min(W,H)*0.0625))`、Bold、Outline 3、Shadow 1、Alignment 2、`MarginL/R=0.06W`；**位置上移到画面下三分之一**（默认 `MarginV=0.26H`）；**去标点**、入场上弹（70%→112%→100%）+ 每 0.6s 轻跳（100%↔103%）、**重点词黄字**（`&H0000FFFF&`）；用 `ass` 滤波器烧录 | `asr.py`（仅取时间轴）/ 生成 ASS + `ffmpeg ass=` / `video_ops.py bgm` / `audio_mix.py` |
| S6 交付 | 给出 Easel Web 媒体直链 | 见「交付」 |

### 命令（项目根运行）

```bash
# S3 音色参考配音（indextts2 零样本；输出 wav 音频，跳过视频验收）
# 字段映射：--prompt → prompt_text（待合成文本）；-a → prompt_simple（音色参考音频）；emo_control_method=与音色参考音频相同
python skills/openclaw/autodl-h3-video/scripts/h3_video.py -w tts \
  -a "三国音色/诸葛亮-老年.mp3" --prompt "买轮椅的妙招，十有九坑。……" \
  --no-verify -o outputs/<topic>/assets/口播_<角色>.wav

# S4a 对口型（角色图 + 口播音频；audio_duration = 音频秒数，1–15）
python skills/openclaw/autodl-h3-video/scripts/h3_video.py -w image_audio \
  -i "outputs/<topic>/assets/角色图.png" -a "outputs/<topic>/assets/口播_<角色>.wav" \
  -r 768p竖 -d 15 -o outputs/<topic>/assets/clip_lipsync.mp4

# S4b 画面生成（两段式，≤10s/段）
python skills/openclaw/autodl-h3-video/scripts/h3_video.py -w multi_image \
  --prompt "<六段式单行>" -i "outputs/<topic>/assets/角色图.png" -r 768p竖 -d 8 \
  -o outputs/<topic>/assets/clip1.mp4
python skills/shared/scripts/video_ops.py concat -i .../clip1.mp4 -i .../clip2.mp4 -o outputs/<topic>/成片_15秒.mp4

# S5 加 BGM（三国 BGM 显式指定）+ 字幕
python skills/shared/scripts/video_ops.py bgm -i 原片.mp4 -o out.mp4 \
  --music "三国音色/三国BGM/诸葛亮BGM.mp3" --music-volume 0.16

# S5 字幕（sanguo 统一样式：雅黑加粗 / Fontsize=min(W,H)*0.0625 / 位置在画面下三分之一 / 去标点 / 入场上弹+每 0.6s 轻跳 / 重点词黄字）
# 用准确文案写 字幕.json（避免 ASR 错字），生成 ASS 并可一并烧录：
python skills/openclaw/sanguo/scripts/sanguo.py ass \
  --spec outputs/<topic>/字幕.json --burn outputs/<topic>/assets/clip_lipsync.mp4 \
  -o outputs/<topic>/成片_15秒.mp4
# 字幕.json 格式：
# {"width":768,"height":1344,"lines":[{"start":0.10,"end":2.75,"text":"买轮椅的妙招，十有九坑。","hl":["九坑"]}]}

# 或字幕 + BGM 一步到位：
python skills/openclaw/sanguo/scripts/sanguo.py post \
  --video outputs/<topic>/assets/clip_lipsync.mp4 --spec outputs/<topic>/字幕.json \
  --bgm 诸葛亮BGM -o outputs/<topic>/成片_15秒.mp4
```

## 规则

1. **音色参考**只能用 `三国音色/` 里你有权使用的角色样本；不克隆无关真人/名人用于误导。
2. **对口型单段 ≤15s**；画面生成单段 ≤10s，需分段拼接。台词音频超过 15s 时先精简文案，或整轨 `atempo`（>1 才加速）压到 15s 内。H3 `tts` 返回 **wav**，`-o` 用 `.wav` 命名。
3. **字幕/口播文案不写进 H3 画面提示词**；后期统一加。提示词**禁用破折号「——」**（H3 丢弃整句）。
4. **BGM** 从 `三国音色/三国BGM/` 按角色/剧情显式指定（不与 koubo 默认曲库混用）。
5. **付费前置**：H3 tts / image_audio / multi_image 均按量计费（¥0.04/0.06/0.10 每秒），跑前给用户范围与预估。
6. **不覆盖原始素材**：只新增文件，不改 `三国音色/`、`人物参考图/` 原素材。
7. **合规红线**（画像 `preferences.md` 优先）：无医疗宣称（治疗/康复/治愈/替代医疗器械）；无「最/第一/100%/顶级」绝对化用语；不虚构销量/好评/案例；老人场景含安全提示。
8. **交付给链接**：成片一律给可播放链接 `http://localhost:7860/api/media/<相对 outputs/ 的路径>`（**不含 `outputs/` 前缀**；中文逐段 URL 编码，如 `api/media/<topic>/<file>.mp4`），不发聊天媒体附件。
9. **字幕统一走 `sanguo.py ass` / `post --spec`**：样式固定为雅黑加粗、`Fontsize=min(W,H)*0.0625`、位置在画面下三分之一（`MarginV=0.26H`）、去标点、入场上弹 + 每 0.6s 轻跳、重点词黄字（`&H0000FFFF&`）；**不要用裸 SRT 默认样式**。文本用 `字幕.json` 提供准确稿（时间轴可用 `asr.py` 取），`hl` 列表为要标黄的重点词。

## Profile 感知

有画像时：文案调性对齐 `style.md`/`audience.md`，红线取自 `preferences.md`；无画像用通用并提示「指定画像更精准」。
