---
name: kefu
description: "客服数字人软广全链路（置顶技能）。native（默认）：文案 → 客服形象图 → H3 multi_image 直出 10s 原生语音视频（不配音、无参考音色）→ koubo 同款硬字幕（ASR 对齐）→ BGM 成片。dub（旧）：图+云配音 → H3 image_audio 对口型。做一个「客服模样的女孩偷偷打电话、直接说台词」的竖屏软广。当用户说「做条客服口播」「数字人说话」「客服偷偷打电话」「对口型视频」「让图里的人照着台词说」时使用；只做场景/旁白口播用 koubo，只生成单段用 autodl-h3-video，只配音用 tts-voiceover。"
layer: produce
---

# kefu · 客服数字人对口型软广全链路

> **配置检查路径铁律**：先 `cd` 到 `AGENTS.md` 末尾给出的 Easel 项目根，确认当前目录有 `.env` 和
> `skills/shared/scripts/`。生图/H3/云 TTS 是否可用只能用 `model_registry.py configured` 与各自
> `check` 判断；不得在 workspace 跑脚本，也不得用 `env` / `printenv` 推断 Key/URL 缺失。

把一个选题做成一条**客服数字人「偷偷打电话、直接说台词」**的竖屏软广成片。

两种链路（`plan.mode` 选择，**默认 `native`**）：

| 链路 | 流程 | 声音 |
|------|------|------|
| `native`（默认） | 形象图 → H3 `multi_image` 直出 **10s** → 硬字幕（ASR 对齐）+ BGM | **视频模型原生语音**：台词写进画面提示词，无需云配音、无需参考音色 |
| `dub`（旧） | 形象图 → 云配音 → H3 `image_audio`（图+音频）对口型 → 硬字幕 + BGM | 云 TTS 音色 + 严格对口型 |

与 `koubo` 的关系：流程同源，字幕样式**逐字节复刻 koubo**；区别在于画面——

| | 画面 | 口型/人声 |
|---|------|------|
| `koubo` | H3 多图场景视频（`multi_image`）+ 旁白 | 无人物对口型，旁白后期配 |
| `kefu native` | H3 `multi_image`（**人像图 + 台词 prompt**） | 人物**直接说话**，模型原生语音 |
| `kefu dub` | H3 `image_audio`（**人像图 + 配音音频**） | 人物**严格对口型**说台词 |

| 环节 | 子命令 | 复用 | 产物 |
|------|--------|------|------|
| S1 文案 + 分镜 | `storyboard` | 本 SKILL | `分镜脚本_<name>.md` |
| S2 链路配置 | `plan` | 本 SKILL | `kefu_plan_<name>.json` |
| S3 客服形象图 | `image` | `ai-image-gen/scripts/ai_image.py` | `assets/<人像>.jpg` |
| S5n 直出（native） | `direct` | `autodl-h3-video/scripts/h3_video.py -w multi_image` | `assets/直出_<name>.mp4` |
| S4 云配音（dub） | `voice` | `tts-voiceover/scripts/tts.py` + ffmpeg | `口播_<name>.mp3` / `字幕_<name>.srt` |
| S5 对口型（dub） | `lipsync` | `h3_video.py -w image_audio` | `assets/对口型_<name>.mp4` |
| S6 字幕 + BGM | `build` | ffmpeg（ass 烧录）+ `video_ops.py bgm`（native 字幕由 `shared/scripts/asr.py` 对成片对齐） | `成片_<N>秒_客服直出_<name>.mp4`（native）/ `..._客服对口型_<name>.mp4`（dub） |
| 一键 | `all` | 按 mode 串联 | 同上 |

脚本路径（相对项目根）：`skills/openclaw/kefu/scripts/kefu.py`

```bash
# 0) 看子命令
python skills/openclaw/kefu/scripts/kefu.py --help

# 1) 出配置模板，填文案/分镜/人像提示词
python skills/openclaw/kefu/scripts/kefu.py plan -o outputs/<topic>/kefu_plan_<name>.json

# 2) 渲染分镜脚本（免费）
python skills/openclaw/kefu/scripts/kefu.py storyboard --plan outputs/<topic>/kefu_plan_<name>.json

# 3) 客服形象图（按量计费，先 --dry-run 看预估，确认后 --yes）
python skills/openclaw/kefu/scripts/kefu.py image   --plan ... --dry-run
python skills/openclaw/kefu/scripts/kefu.py image   --plan ... --yes

# 4n) native 直出（H3 multi_image 原生语音；按量计费，先 --dry-run 看预估，确认后 --yes）
python skills/openclaw/kefu/scripts/kefu.py direct  --plan ... --dry-run
python skills/openclaw/kefu/scripts/kefu.py direct  --plan ... --yes

# 4d) dub 旧链路：云配音 + 1.15x + 去标点字幕
python skills/openclaw/kefu/scripts/kefu.py voice   --plan ...

# 5d) dub 旧链路：对口型（按量计费，先 --dry-run 看预估，确认后 --yes）
python skills/openclaw/kefu/scripts/kefu.py lipsync --plan ... --dry-run
python skills/openclaw/kefu/scripts/kefu.py lipsync --plan ... --yes

# 6) 字幕 + BGM → 成片（免费后期）
python skills/openclaw/kefu/scripts/kefu.py build   --plan ...

# 一键全链路（生图+H3 计费环节，需 --yes）
python skills/openclaw/kefu/scripts/kefu.py all     --plan ... --yes
```

## 链路配置（plan.json）

| 字段 | 说明 |
|------|------|
| `mode` | `native`（默认，H3 直出原生语音）/ `dub`（云配音 + image_audio 对口型） |
| `topic` | 主题目录名（`outputs/<topic>/`），人类可读的具体项目名 |
| `name` | 产物后缀，如 `偷偷客服_v2` |
| `profile` | 画像名（可空）；有画像时文案/音色/红线对齐画像 |
| `title` / `platform` | 标题 / 发布平台 |
| `resolution` | H3 画幅（默认 `768p竖`） |
| `duration` | 目标成片秒数（native **固定 10s**；dub 单段上限 15s） |
| `spoken` | 读音替换表，如 `{"218": "二幺八"}`（见「读音约定」） |
| `voiceover[]` | 台词逐句数组（一行一句，同时是字幕句；native 由模型原生念出） |
| `shots[]` | 分镜：`t` / `scene` / `vo` / `sub`（渲染进分镜脚本） |
| `persona_image` | `prompt` / `size`(默认 1440x2560) / `file`（人像图文件名，落 `assets/`） |
| `speech_prompt` | native：H3 `multi_image` 的画面+表演提示词（人设 + 偷偷动作 + 不笑 + 对口型；台词由脚本自动追加；**禁破折号「——」**） |
| `lipsync_prompt` | dub：H3 `image_audio` 画面提示词 |
| `voice` / `speed` | dub 云音色（默认 `claire`）/ 最终语速（默认 `1.15`） |
| `bgm` / `bgm_volume` | BGM（默认 `auto` 按关键词匹配）/ 音量（默认 `0.16`） |
| `asr_model` | native 字幕对齐用的 ASR 模型（默认 `small`） |

## 固定约定（S4–S6，可用参数覆盖）

| 项 | 默认 | 说明 |
|----|------|------|
| 出片 | native 10s | `multi_image` 一次性出 10s（不拼接）；dub 单段上限 15s |
| 声音 | native 原生语音 | 台词写进 prompt 由视频模型发声；**不提供参考音色、不做后期配音** |
| 云音色（dub） | `FunAudioLLM/CosyVoice2-0.5B:claire` | 温柔女声；`VOICE_NARRATOR_VOICE_ID` 可覆盖 |
| 合成语速（dub） | `1.0`（自然） | 直传 speed>1 会截尾吞字；**变速只在整轨过一次 `atempo`** |
| 最终语速（dub） | `1.15` | 本工作区偏好略快；`--speed 1.0` 回自然 |
| 字幕 | 去标点 | **数字内小数点保留**（`13.8公斤` 不会被清成 `138公斤`） |
| 字幕样式 | **与 koubo 完全一致** | 微软雅黑 / 加粗(Bold=-1) / 白字黑边(Outline=3,Shadow=1) / Alignment=2 底部居中 / 字号 `max(34,int(min(W,H)*0.0625))` / MarginL,R=`W*0.06` / MarginV=`H*0.11` |
| BGM | 按主题/脚本关键词自动匹配 | 亲情·爸妈 → 《归家步履踏歌来》；出行 → 《一路都是风景》…（同 koubo 规则表） |
| BGM 音量 | `0.16` | 旁白+BGM 默认开启闪避 |
| 片长 | 满长不压缩 | native 固定 10s；dub 口播提前说完时尾部保留空镜/BGM 收尾，不裁画面 |

## 字幕样式（务必与 koubo 一致）

`build` 用 ASS 硬烧录，样式头与 koubo 的 `ASS_HEAD` 相同：

```
Style: Sub,Microsoft YaHei,{size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,{ml},{mr},{mv},1
size = max(34, int(min(W, H) * 0.0625)) ; ml = mr = int(W * 0.06) ; mv = int(H * 0.11)
```

> 改字幕样式等于改本条约定；若 koubo 后续调整样式，务必同步本处，二者必须逐字节一致。

## H3 成本

| 分辨率 | ¥/秒 | 15s |
|--------|------|-----|
| 480p | 0.04 | ≈¥0.60 |
| 768p（默认） | 0.06 | ≈¥0.90 |
| 1080p | 0.10 | ≈¥1.50 |

`image`/`lipsync`/`all` 无 `--yes` 时直接拒绝执行（先报预估）；`--dry-run` 只预估不提交。**付费前先给用户确认范围。**

## 规则

1. **先分镜后付费** — 制作前先出 `分镜脚本_<name>.md` 给用户审核，通过再跑计费环节。
2. **单段上限** — native `multi_image` 10s；dub `image_audio` 15s；更长需求需分段后 `video_ops.py concat`。
3. **提示词禁破折号「——」**、禁描述画面内文字/字幕（H3 会丢弃整句或手写字崩）。
3b. **读音约定** — 台词里的型号/编号数字按口语逐位书写，`1` 写作「幺」（218 → 二幺八）；小数照常（13.8 → 十三点八）。用 `plan.spoken` 替换，字幕同步。 [2026-10-10 用户定]
4. **字幕与 koubo 一致** — 去标点、保数字小数点、微软雅黑 / 加粗 / 白字黑边 / 底部居中；发现不一致直接判失败。
5. **不吞字** — 口播一律 1.0 自然语速合成，变速只在整轨 `atempo`；交付前 `silencedetect` 复核。
6. **不合格不交付** — 验收（时长 / 画幅 / >1MB / 末字；native 另需**音轨非静音**）全绿才交付；失败保留断点在 `assets/`。
7. **合规红线**（画像 `preferences.md` 优先）— 无医疗宣称；无「最/第一/100%」绝对化用语；不虚构活动/销量/好评；老人场景含安全提示。
8. **不覆盖原始素材** — 只新增文件，不改 `assets/` 原素材与既有成片。
9. **交付给链接** — 出片给可播放链接：`http://localhost:7860/api/media/<相对 outputs 的路径>`（路径**不含** `outputs/` 段，中文逐段 URL 编码），如 `.../api/media/<topic>/成片_<N>秒_客服对口型_<name>.mp4`。
10. **折展 / 移动场景用两张参考图** — 有明确折叠或展开要求时必须给「展开态 + 折叠态」两张图，且**折叠↔展开过程须控制在 0.3 秒内**一气呵成（防失真）；移动场景必须给「45° + 侧面」两张图（加深细节、防失真）。单图先补齐再生成，详见 `skills/shared/references/video-reference-images.md`。 [2026-10-03 用户定]

## 输出（`outputs/<topic>/`）

- `分镜脚本_<name>.md`、`kefu_plan_<name>.json`
- native：`assets/直出_<name>.mp4`、`字幕_<name>.srt`（ASR 对齐）
- dub：`口播_<name>.mp3`、`字幕_<name>.srt`、`assets/对口型_<name>.mp4`
- `assets/<人像>.jpg`
- `成片_<N>秒_客服直出_<name>.mp4`（native）/ `成片_<N>秒_客服对口型_<name>.mp4`（dub）— 最终成片

中间文件进 `outputs/_scratch/`。

## 排查

```bash
# 末字被吞 / 段中磕巴：看音频静音分布
ffmpeg -hide_banner -i outputs/<topic>/口播_<name>.mp3 -af silencedetect=noise=-35dB:d=0.20 -f null -
# 字幕是否与 koubo 一致：比对 ASS 样式行
grep -n "^Style: Sub" outputs/_scratch/kefu_sub.ass
# native 音轨是否有人声 / 是否静音
ffmpeg -hide_banner -i outputs/<topic>/成片_10秒_客服直出_<name>.mp4 -af volumedetect -f null -
# native 字幕与成片是否对齐（重跑 ASR 核对）
python skills/shared/scripts/asr.py transcribe -i outputs/<topic>/assets/直出_<name>.mp4 -o outputs/_scratch/check.srt --language zh --model small
```

## Profile 感知

有画像时从 `preferences.md` 读红线与偏好音色/语速/BGM 风格覆盖默认；文案调性对齐 `style.md`/`audience.md`。无画像用默认并提示「指定画像效果更好」。
