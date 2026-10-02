---
name: autodl-h3-video
description: >-
  AutoDL.Art MiniMax H3 视频生成（自家通道）：文生/多图参考/首尾帧/图+音频对口型，带自动验收与批量续传。
  当用户说"用H3生视频""autodl生视频""MiniMax H3""参考图做视频（H3工作流）"时使用。
  与 ai-video-gen 的区别：ai-video-gen 走统一 provider 配置的云端视频服务；本 SKILL 固定走 autodl.art 的 ComfyUI 工作流通道（读取 AUTODL_API_KEY）。
layer: produce
---

# AutoDL.Art MiniMax H3 视频生成

> 包装 AutoDL.Art 的 ComfyUI 工作流 REST API（H3 全家族），走 `scripts/h3_video.py`。
> 流程：POST 提交 → GET 轮询（20s）→ 下载 → ffprobe 自动验收；支持单条 / 批量（并发）/ 断点续传 / 成本日志。
> 本 SKILL 为本地自定义扩展（非 Easel 上游技能），与上游技能并存。

## ⚠️ 环境依赖

| 依赖 | 说明 |
|------|------|
| AUTODL_API_KEY | autodl.art token（https://autodl.art/large-model/tokens 创建，分组选 ComfyUI），已配在项目根 `.env` |
| 网络 | 直连 autodl.art（SSL 抖动已内置重试） |
| ffprobe | 可选（下载后自动验收用；缺失只跳过验收） |

## 输入

| 字段 | 必填 | 说明 |
|------|------|------|
| prompt | 是 | 提示词（H3 规范：base 模式三字段 / Ref2VA 六段式） |
| images | 视工作流 | 参考图：本地文件自动转 base64（>1280px 自动压缩），或公网 URL |
| workflow | 推荐 | `multi_image`（多图参考，默认）/ `image_audio`（图+音频对口型）/ `text2video` / `first_last`（首尾帧）/ `tts` |
| resolution | 可选 | 480p/768p/1080p × 竖/横（默认 768p竖；价格 ¥0.04 / 0.06 / 0.10 每秒） |
| duration | 可选 | 视频 1-10s；对口型 1-15s |

## 执行

脚本路径（相对项目根）：`skills/openclaw/autodl-h3-video/scripts/h3_video.py`

```bash
# 文生视频
python <skill>/scripts/h3_video.py -w text2video --prompt "..." -r 768p竖 -d 5 -o out.mp4
# 多图参考（最常用）
python <skill>/scripts/h3_video.py -w multi_image --prompt "..." -i 图1.jpg -i 图2.jpg -d 10 -o out.mp4
# 图+音频对口型
python <skill>/scripts/h3_video.py -w image_audio --prompt "台词" -i 图.jpg -a 音.wav -d 8 -o talk.mp4
# 批量（选题文件：编号.+提示词 两行一条；并发+续传）
python <skill>/scripts/h3_video.py -w multi_image --ideas 选题.txt -i 图.jpg --out-prefix video --concurrency 10
# 断点续传
python <skill>/scripts/h3_video.py ... --resume
```

## 规则

1. 默认 768p竖；1080p 更贵（¥0.10/秒），批量前先单条验证。
2. 台词/字幕**禁用破折号"——"**（H3 会丢弃整句）。
3. 下载后自动验收（时长±1s / 宽高比 / 大小>1MB）；不合格重跑。
4. 成本与验收记录在输出目录 `h3_gen_log.jsonl`。
5. POST 不重试（防重复扣费）；GET 轮询 5 次 / 下载 4 次重试已内置。

## 参考来源

AutoDL.Art（https://autodl.art）ComfyUI 工作流 REST 封装；
H3 官方提示词规范见 Hermes「autodl」技能 references/prompt-writing.md。
