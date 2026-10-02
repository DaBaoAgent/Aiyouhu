---
name: koubo
description: "口播广告全链路（置顶技能）：从选题/文案 → H3 两段式提示词 → 调 H3 生成两段并拼接 → 云配音 + 无标点硬字幕 + 自动匹配 BGM → 满长成片。一个技能跑通竖屏口播广告从 0 到成片。当用户说「做条口播广告」「从文案到成片」「生成文案并拍出来」「H3 提示词」「两段拼接」「给这条片子配旁白」「配音加 BGM」「旁白吞字/磕巴」「语速/停顿调一下」「按上次那套参数再来一版」时使用；只做单环节可单用对应子命令或邻近技能（copywriting / autodl-h3-video / tts-voiceover / audio-mix）。"
layer: produce
---

# koubo · 口播广告全链路

> **配置检查路径铁律**：先 `cd` 到 `AGENTS.md` 末尾给出的 Easel 项目根，确认当前目录有 `.env` 和
> `skills/shared/scripts/`。云 TTS / H3 是否可用只能用 `model_registry.py configured` 与各自 `check` 判断；
> 不得在 workspace 跑脚本，也不得用 `env` / `printenv` 推断 Key/URL 缺失。

把一个选题做成一条竖屏口播广告成片。五个环节串成一条确定性流水线，既能一键跑通，也能只跑其中一环：

| 环节 | 子命令 | 复用 | 产物 |
|------|--------|------|------|
| S1 文案 | （读 `copywriting` + 画像，人工/模型产出） | `skills/openclaw/copywriting`、`references/copy-frameworks.md` | `文案初稿_<name>.md` |
| S2 链路配置 | `plan-template` | 本 SKILL | `koubo_plan_<name>.json` |
| S3 H3 提示词 | `h3plan` | 本 SKILL（六段式 + 两段切分） | `H3视频提示词_<name>.md` |
| S4 两段生成 + 拼接 | `h3gen` | `autodl-h3-video/scripts/h3_video.py` + `video_ops.py concat` | `成片_<N>秒.mp4` |
| S5 配音字幕 BGM | `build` | `voice_clone.py` + `audio_mix.py` + ffmpeg | `成片_<N>秒_配音字幕BGM_<name>.mp4` |
| 一键 | `all` | S3→S4→S5 | 同上 |

脚本路径（相对项目根）：`skills/openclaw/koubo/scripts/koubo.py`

```bash
# 0) 看子命令
python skills/openclaw/koubo/scripts/koubo.py --help

# 1) 出配置模板，填文案/分镜/六段式提示词
python skills/openclaw/koubo/scripts/koubo.py plan-template -o outputs/<topic>/koubo_plan_<name>.json

# 2) 生成 H3 提示词文档 + 运行命令（不调 H3、不花钱）
python skills/openclaw/koubo/scripts/koubo.py h3plan --plan outputs/<topic>/koubo_plan_<name>.json

# 3) 两段生成 + 拼接（按量计费，先 --dry-run 看预估，确认后 --yes）
python skills/openclaw/koubo/scripts/koubo.py h3gen --plan ... --dry-run
python skills/openclaw/koubo/scripts/koubo.py h3gen --plan ... --yes

# 4) 配音 + 无标点字幕 + BGM → 成片
python skills/openclaw/koubo/scripts/koubo.py build --plan outputs/<topic>/koubo_plan_<name>.json

# 一键全链路（H3 + 后期）
python skills/openclaw/koubo/scripts/koubo.py all --plan ... --yes
```

## 链路配置（plan.json）

`plan-template` 输出的结构；`build`/`h3plan`/`h3gen`/`all` 都读它。缺省项由 plan 补全，命令行参数优先。

| 字段 | 说明 |
|------|------|
| `topic` | 主题目录名（`outputs/<topic>/`），人类可读的具体项目名 |
| `name` | 产物后缀，如 `15秒_v1` |
| `profile` | 画像名（可空）；有画像时文案/音色/红线对齐画像 |
| `hot_topic` / `title` | 热点/选题；标题（含热点关键词） |
| `platform` | `["抖音","视频号"]` 等 |
| `workflow` / `resolution` | H3 工作流（默认 `multi_image`）/ 画幅（默认 `768p竖`） |
| `duration` | 目标成片秒数（≥ 原片长度） |
| `copy` | `titles` / `body` / `cta` / `tags`（文案产物，供发布用） |
| `voiceover` | 口播逐句数组（一行一句，同时是字幕句） |
| `segments[]` | 每段：`id` / `duration`(1–10s) / `shots` / `refs[]`(放 assets/) / `prompt{六段式}` / `voiceover` |

## S1 · 文案（人工+模型，非脚本）

1. 读画像 `easel-profiles/<画像>/{identity,style,audience,preferences}.md`，红线原样遵守。
2. 按 `skills/openclaw/copywriting/SKILL.md` 的框架（AIDA/PAS/FAB…）产出：**标题（2–3 备选，含热点关键词）→ 口播分镜（镜/时长/画面/口播/字幕）→ 视频配文 → CTA → 话题标签**。
3. 口播控制在目标时长内：中文约 **4 字/秒**（1.15x 语速下约 4.5 字/秒）；15s 片建议 8–10 句短句。
4. **字幕/口播不写进 H3 提示词**（`multi_image` 不出音频，AI 视频手写字易崩）；后期统一加。
5. 合规自检（见「规则」）后写入 `outputs/<topic>/文案初稿_<name>.md`，并把口播逐句填进 plan 的 `voiceover`。

## S3 · H3 提示词（六段式 + 两段切分）

- **单段上限 10s**：15s 拆 **8 + 7**，20s 拆 10+10，以此类推；每段一个 `segments[]` 条目。
- 每段提示词按 **六段式** 填写（`prompt` 六个键，顺序固定）：
  `参考主体` / `镜头景别` / `主体动作` / `场景环境` / `光线风格` / `画质约束`。
- 拼接为单行、字段间「；」分隔；**禁用破折号「——」**（H3 会丢弃整句，脚本会直接拦截）。
- 参考图放 `outputs/<topic>/assets/`，`refs` 写文件名；提示词里不出现文字/字幕/水印/logo 描述。
- `h3plan` 会把以上写成 `H3视频提示词_<name>.md`（含每段运行命令 + 拼接命令 + 成本预估）。

## S4 · 两段生成 + 拼接

`h3gen` 逐段调 `h3_video.py -w <workflow> --prompt <六段式单行> -i <refs...> -r <res> -d <dur> -o assets/clipN_<shots>.mp4`，
全部完成后用 `video_ops.py concat` 拼成 `成片_<N>秒.mp4`（脚本自带 ffprobe 验收：时长±1s / 画幅 / >1MB）。

## 固定约定（S5，默认值可用参数覆盖）

| 项 | 默认 | 说明 |
|----|------|------|
| 云音色 | `FunAudioLLM/CosyVoice2-0.5B:claire` | 温柔女声；`VOICE_NARRATOR_VOICE_ID` 可覆盖 |
| 合成语速 | `1.0`（自然） | **一律自然语速合成**——直传 TTS speed>1 会截尾吞字（实测 1.2x 把「门」吞掉） |
| 最终语速 | `1.15` | 合成后整轨过一次 `atempo`（本工作区偏好略快；`--speed 1.0` 回自然） |
| 句间停顿 | `0.25s` | 紧凑节奏；传 `--gap auto` 则自动撑满 `--duration`（取值 0.15–0.60s） |
| 每句候选数 | `6` | 小模型同句多合成节奏随机、常插内部怪停顿；多合成几条再挑（`--tries`） |
| 每句尾部补静音 | `0.10s` | 防止最后一个字被削掉/吞字 |
| 字幕 | 去标点 | **数字内小数点保留**（`13.8公斤` 不会被清成 `138公斤`） |
| BGM | 按主题/脚本关键词自动匹配 | 自动裁掉开头**静音/弱起**（‑6dB 自适应探测，`--no-bgm-trim` 关闭） |
| BGM 音量 | `0.16` | 旁白+BGM 默认开启闪避 |
| 片长 | **原片满长（不压缩）** | 旁白提前说完时，**尾部保留 BGM + 原画面空镜收尾，不裁原片**；`--duration` 指定更长目标则末帧定格补足；短于口播直接报错 |

### S5 内部流程（build 做什么）

逐句合成 N 条候选 → 精选（`silencedetect` 剔除含内部停顿者，再取时长中位最稳一条）→ 裁头尾静音转 PCM →
自动分配句间停顿 → **一次干净拼接**（必要时整轨 `atempo`）→ 写 SRT/ASS（去标点）→ BGM 去开头静音 + 混音
（旁白补静音到目标时长，BGM 才铺满）→ 烧字幕满长渲染 → 打印验收表。任一不合格退出码 2，**不交付**。

## H3 成本

| 分辨率 | ¥/秒 | 15s |
|--------|------|-----|
| 480p | 0.04 | ≈¥0.60 |
| 768p（默认） | 0.06 | ≈¥0.90 |
| 1080p | 0.10 | ≈¥1.50 |

`h3gen` 无 `--yes` 时直接拒绝执行（先报预估）；`--dry-run` 只预估不提交。**付费前先给用户确认范围。**

## BGM 自动匹配

按「主题名 + 脚本全文」关键词打分，取最高分（并列取表中靠前者）：

| 关键词 | 曲目 |
|--------|------|
| 出行/出游/旅行/旅游/风景/在路上/自驾/高铁/远行 | 一路都是风景 |
| 亲情/回家/团圆/温暖/爸妈/父母/陪伴/孝 | 归家步履踏歌来 |
| 清晨/希望/阳光/励志/开始 | 第一缕阳光 |
| 夏日/清爽/气泡/轻快/夏天 | 夏日慢时光 |
| 海边/度假/沙滩/海风 | 惬意的黄昏海风 |
| 悠闲/放松/日常/治愈 | 轻快悠闲 |
| 节日/喜庆/过年/春节/国庆/热闹 | 欢喜欢快喜庆 |
| 搞笑/幽默/沙雕/整活 | 滑稽搞笑 |

默认目录 `D:\自动剪辑\BGM\抖音最火BGM`（`--bgm-dir` 可改）；未命中用默认曲《一路都是风景》。

## 输出（`outputs/<topic>/`）

- `文案初稿_<name>.md`、`koubo_plan_<name>.json`、`H3视频提示词_<name>.md`
- `成片_<N>秒.mp4` — H3 两段拼接后的原片（S4）
- `成片_<N>秒_配音字幕BGM_<name>.mp4` — 最终成片（S5）
- `口播_<name>.mp3` / `口播BGM_<name>.mp3` / `口播_<name>.srt` / `字幕_<name>.ass` / `口播稿_<name>.txt`

中间文件进 `outputs/_scratch/koubo_<name>/`（每句候选 `line<i>_try<k>.mp3`、裁静音后 `line<i>_clean.wav`；
`--reuse-parts` 可断点续跑）。**纯后处理调语速/停顿无需重调 TTS**：把上次 `koubo_<旧name>/line*_try*.mp3`
拷进 `koubo_<新name>/` 再带 `--reuse-parts`。

## 交付（出片后）

成片**直接给链接**，不在聊天里发媒体附件 / 媒体卡片。

- 链接 = Easel Web 媒体直链：`http://localhost:7860/api/media/<outputs 相对路径>`，路径按段 URL 编码（中文等非 ASCII 字符逐段编码），例如 `outputs/<topic>/成片_<N>秒_<name>.mp4`。
- 交付前先确认 Easel Web 在运行（`http://localhost:7860/` 可达）；没在跑先提示用户双击项目根 `启动Easel.cmd`（或代为启动）再给链接。
- 本机预览链接只在本机有效、不可对外分发；对外投放链接用 `skill-short-link`（UTM / 短链，需公网落地页），两者不混用。

## 规则

1. **原片不压缩** — 目标时长 ≥ 原片长度；不足用末帧定格补足，绝不裁掉原有画面。
   **旁白早于片尾结束时，保留尾部 BGM + 空镜收尾，不把视频裁短**（2026-10-02 用户定）。
2. **不吞字、不磕巴** — 根因是云端小模型（CosyVoice2-0.5B）同句多合成**节奏随机**：会插入内部怪停顿（听感磕巴）或让末字发虚。对策：每句合成 N 条候选 → 用 `silencedetect` 剔除含内部停顿者 → 取时长中位数附近最稳一条；TTS 一律 1.0 自然语速合成（直传 speed>1 会截掉末字），要变速只在整轨过一次 `atempo`；交付前用 `silencedetect` 复核成轨（只应有句间停顿）+ ASR 复核末字。
3. **H3 分段** — 单段 ≤10s；提示词禁破折号「——」、禁电子文字/字幕描述。
4. **字幕去标点但保数字** — 数字内小数点保留；发现残留标点直接判失败。
5. **付费前置** — H3 与云 TTS 均按量计费；跑前给用户确认范围；H3 未加 `--yes` 不执行。
6. **不合格不交付** — 验收表全绿才 `KOUBO_OK`；失败保留断点在 `outputs/_scratch/koubo_<name>/`。
7. **合规红线**（画像 `preferences.md` 优先）— 无医疗宣称（治疗/康复/治愈/替代医疗器械）；无「最/第一/100%/顶级」绝对化用语；不虚构销量/好评/案例；不违规导流；老人场景含安全提示。
8. **不覆盖原始素材** — 只新增文件，不改 `assets/` 原素材与既有成片。
9. **交付给链接** — 出片一律给出可播放链接（Easel Web 媒体直链 `/api/media/<outputs 相对路径>`），不在聊天里发媒体附件 / 卡片；见「交付（出片后）」。 [2026-10-02 用户定]

## 排查

```bash
# 旁白“末字被吞 / 段中磕巴”：看候选与成轨的静音分布
ffmpeg -hide_banner -i outputs/_scratch/koubo_<name>/line0_try0.mp3 -af silencedetect=noise=-35dB:d=0.20 -f null -
# 成轨应只有句间停顿；某句出现段中短静音 = 内部磕巴，重跑该句候选
```

## Profile 感知

有画像时从 `preferences.md` 读红线与偏好音色/语速/BGM 风格覆盖默认；文案调性对齐 `style.md`/`audience.md`。无画像用默认并提示「指定画像效果更好」。
