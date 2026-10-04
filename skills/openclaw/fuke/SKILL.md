---
name: fuke
description: "爆款视频复刻全链路（置顶技能）：拿一条参考视频（链接或本地文件），用项目根的 hypit 引擎把它的钩子、画面、字幕、B-roll、配音拆成可复用工作流，再换成我们自己的产品、人物和文案，生成并导出可发布成片到 outputs/。当用户说「复刻这条视频」「照着这个爆款做一条」「克隆这条广告」「抄爆款结构换我们的产品」「参考视频二创」时使用；做客服对口型用 kefu，做场景旁白口播用 koubo，只生成单段用 autodl-h3-video，只切片用 clipify。"
layer: produce
---

# fuke · 爆款视频复刻全链路

> **路径铁律**：先 `cd` 到 `AGENTS.md` 末尾的 Easel 项目根，确认当前目录有 `.env`、`skills/shared/scripts/`、`hypit/`。hypit 是否可用只看 `hypit version`；不得在 workspace 跑脚本，也不得用 `env` / `printenv` 推断 Key 缺失。

把一条**已验证的爆款视频**复刻（clone）成我们自己的成片：拆工作流 → 换目标 → 生成 → 导出。
引擎是项目根的新项目 `hypit/`（`@hypit/hypit`，入口 `bin/hypit.mjs`）；它的创作知识在 `hypit/skills/hypit/SKILL.md` 及其同目录的参考页，**每个环节动手前先读对应页面**。

## 与相邻 SKILL 的边界

| 场景 | 用 |
|------|----|
| 复刻一条参考视频的工作流，并换成我们的产品/人物/文案 | **fuke** |
| 客服数字人偷偷打电话、直接对口型（无参考视频） | `kefu` |
| 口播广告 / 场景旁白成片（无参考视频） | `koubo` |
| 只生成一段图生视频 | `autodl-h3-video` |
| 只把长视频切成短视频 | `clipify` |

## 输入

- **参考**：视频链接（抖音/小红书/YouTube/bilibili…）或本地视频文件（必填）
- **目标改造**：换成什么产品、人物、卖点、文案、语言（默认画像「爱优护电动轮椅软广号」，产品=电动轮椅）
- 可选：画幅、目标时长、发布平台、要保留或替换的结构

## 输出（`outputs/<topic>/`）

- `成片_复刻_<name>.mp4` — 最终成片（成品放项目目录根）
- `复刻说明.md` — 参考结构 + 目标改造 + 执行记录
- `assets/hypit/` — hypit 工作区（references/ productions/ runs/ .hypit/ 等中间件）

## 执行步骤

### S0 · 环境自检（免费）
```bash
python skills/openclaw/fuke/scripts/fuke.py check
```

### S1 · 立项目 + 收参考
```bash
python skills/openclaw/fuke/scripts/fuke.py workspace --topic "<主题>"
python skills/openclaw/fuke/scripts/fuke.py fetch --topic "<主题>" --url "<参考视频链接>"
```
本地文件直接复制进工作区 `references/<name>/source.mp4`。
首次使用在 hypit 工作区选 Runtime Profile：
```bash
node hypit/bin/hypit.mjs runtime init
```

### S2 · 读参考（免费，先读 hypit 的 creation/reference-video 与 creation/project-files）
```bash
node hypit/bin/hypit.mjs transcribe "<video>" --language zh --to "<transcript.json>"
node hypit/bin/hypit.mjs media tile "<video>" --start 0 --end 12 --every 1 --to "<evidence/opening.jpg>"
```
把整片解读与逐时细节写进 `ANALYSIS.md` / `TIMELINE.md`（存 `references/<name>/`），并把发现说给用户听。

### S3 · 目标改造（先读 hypit 的 creation/transformations、creation/brief、playbooks/craft/image-direction 等）
写 `BRIEF.md`（用户目标/约束/已确认预算）与 `TREATMENT.md`（创作答案），产出发作者源 `.svml` 与 Run `.svrun`。

### S4 · 计划 + 成本（必须，先确认再花钱）
```bash
node hypit/bin/hypit.mjs plan "<build.svrun>"
node hypit/bin/hypit.mjs pricing "<build.svrun>"
```
把工作量与预估费用交给用户确认范围，通过后才进入 S5。

### S5 · 生成（Build，按量计费）
```bash
node hypit/bin/hypit.mjs build "<build.svrun>" --follow
node hypit/bin/hypit.mjs status <build-id>
```
Build 时间较长时先给用户进度，不要空等。

### S6 · 导出 + 自检 + 交付
```bash
python skills/openclaw/fuke/scripts/fuke.py export --topic "<主题>" --build <build-id> --output <Output名> --filename "成片_复刻_<name>.mp4"
python skills/openclaw/fuke/scripts/fuke.py verify --topic "<主题>" --file "成片_复刻_<name>.mp4"
python skills/openclaw/fuke/scripts/fuke.py link --topic "<主题>" --file "成片_复刻_<name>.mp4"
```

## 环境与凭据

- **Runtime Profile**：`hypit runtime init`（写入并选中可编辑的 `hypit.runtime.json`）/ `hypit runtime use <profile>`。
- **生成/对齐服务**：HypiHub（推荐）或自带 API Key 的 BYOK；凭据用 `hypit auth status|login <endpoint>` 管理，值进系统凭据库，**不写进文件、命令参数或聊天**。
- **付费红线**：Build 前必须 `plan` + `pricing`，把预估给用户确认；超出已确认范围（工作、费用、账号）要重新确认。

## 合规红线（画像 `preferences.md` 优先）

- 无医疗宣称；无「最/第一/100%」绝对化用语；不虚构活动/销量/好评；老人场景含安全提示。
- 成片对外文案不带任何工具、模型、配置或内部路径痕迹。

## 规则

1. 先分析后生成，先 `plan` 后 `build`；参考理解不完整不进入生成。
2. 参考真值与目标真值分开存放；一份参考可服务多条目标，不复制参考本身。
3. 产出写 `outputs/<topic>/`：成品放项目根，中间件进 `assets/`。
4. 不覆盖 `assets/` 原素材与既有成片，只新增文件。
5. 自检（非空 / 时长 / 画幅 / 可播放）全绿才交付；失败保留断点在 `assets/hypit/`。
6. 交付给可播放媒体直链（用 `fuke.py link`）。
7. **折展 / 移动场景用两张参考图** — 有明确折叠或展开要求时必须给「展开态 + 折叠态」两张图，且**折叠↔展开过程须控制在 0.3 秒内**一气呵成（防失真）；移动场景必须给「45° + 侧面」两张图（加深细节、防失真）。单图先补齐再生成，详见 `skills/shared/references/video-reference-images.md`。 [2026-10-03 用户定]

## Profile 感知

有画像时从 `preferences.md` 读红线与产品/人称/语气偏好，文案与画面方向对齐 `style.md` / `audience.md`；无画像用默认并提示「指定画像效果更好」。
