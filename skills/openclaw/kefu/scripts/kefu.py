#!/usr/bin/env python3
"""kefu · 客服数字人对口型软广全链路

两种链路（`plan.mode` 选择，默认 `native`）：
  native（默认）：客服形象图(image) → H3 multi_image 直出 10s **原生语音**视频(direct)
          → koubo 同款硬字幕（对成片 ASR 对齐）+ BGM → 成片。
          **无云配音、无参考音色**：台词写进画面提示词，由视频模型原生发声。
  dub（旧链路）：客服形象图(image) → 云配音(voice, 1.15x) → H3 image_audio 对口型(lipsync)
          → 硬字幕 + BGM → 成片。

与 koubo 分界：koubo 走 H3 多图场景视频 + 旁白；kefu 让参考图里的人**直接说台词**。

读音约定：台词里的型号/编号数字按口语逐位书写，`1` 写作「幺」（218 → 二幺八）；
小数照常（13.8 → 十三点八）。用 `plan.spoken` 做文字替换。
字幕样式与 koubo **逐字节一致**：微软雅黑 / 加粗 / 白字黑边 / 底部居中 / 字号≈短边6.25% / 去标点(保数字小数点)。

路径铁律：先 cd 到项目根（含 .env 与 skills/shared/scripts/）。

用法：
  python skills/openclaw/kefu/scripts/kefu.py plan       -o outputs/<topic>/kefu_plan_<name>.json
  python skills/openclaw/kefu/scripts/kefu.py storyboard --plan <plan.json>
  python skills/openclaw/kefu/scripts/kefu.py image      --plan <plan.json> [--dry-run|--yes]
  python skills/openclaw/kefu/scripts/kefu.py voice      --plan <plan.json>
  python skills/openclaw/kefu/scripts/kefu.py direct     --plan <plan.json> [--dry-run|--yes]   # native 直出（原生语音）
  python skills/openclaw/kefu/scripts/kefu.py lipsync    --plan <plan.json> [--dry-run|--yes]   # dub 旧链路
  python skills/openclaw/kefu/scripts/kefu.py build      --plan <plan.json>
  python skills/openclaw/kefu/scripts/kefu.py all        --plan <plan.json> [--dry-run|--yes]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# ── 固定约定（与 koubo 对齐）─────────────────────────────────────────────
DEFAULT_VOICE = "FunAudioLLM/CosyVoice2-0.5B:claire"
DEFAULT_RES = "768p竖"
DEFAULT_FINAL_SPEED = 1.15
DEFAULT_IMG_SIZE = "1440x2560"
DEFAULT_BGM_VOLUME = 0.16

H3_MAX_AUDIO_SEC = 15                                          # image_audio 单段上限
H3_MAX_VIDEO_SEC = 10                                          # multi_image 直出单段上限
DEFAULT_DURATION = {"native": 10, "dub": 15}                   # native 一次性 10s；dub 到 15s
H3_PRICE = {"480p": 0.04, "768p": 0.06, "1080p": 0.10}         # ￥/秒
IMG_PRICE = 0.20                                               # 生图粗估 ￥/张

DEFAULT_BGM_DIR = r"D:\自动剪辑\BGM\抖音最火BGM"
DEFAULT_BGM = "一路都是风景"

BGM_RULES: list[tuple[tuple[str, ...], str]] = [
    (("出行", "出游", "旅行", "旅游", "风景", "在路上", "自驾", "高铁", "远行"), "一路都是风景"),
    (("亲情", "回家", "团圆", "温暖", "爸妈", "父母", "陪伴", "孝"), "归家步履踏歌来"),
    (("清晨", "希望", "阳光", "励志", "开始"), "第一缕阳光"),
    (("夏日", "清爽", "气泡", "轻快", "夏天"), "夏日慢时光"),
    (("海边", "度假", "沙滩", "海风"), "惬意的黄昏海风"),
    (("悠闲", "放松", "日常", "治愈"), "轻快悠闲"),
    (("节日", "喜庆", "过年", "春节", "国庆", "热闹"), "欢喜欢快喜庆"),
    (("搞笑", "幽默", "沙雕", "整活"), "滑稽搞笑"),
]

PUNCT = '。，、！？；：""\'\'（）《》〈〉—－…·～,.!?;:"\'()[]{}<>'

# 字幕样式：与 koubo 完全一致（微软雅黑 / 加粗 / 白字黑边 / 底部居中）
ASS_HEAD = """[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,Microsoft YaHei,{size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,{ml},{mr},{mv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


# ── 基础工具 ────────────────────────────────────────────────────────────
def fail(msg: str, code: int = 1):
    print(f"错误：{msg}", file=sys.stderr)
    raise SystemExit(code)


def find_root() -> Path:
    here = Path(__file__).resolve()
    for p in [here, *here.parents]:
        if (p / "skills" / "shared" / "scripts" / "tts.py").is_file():
            return p
    fail("找不到项目根（未定位到 skills/shared/scripts/tts.py）")


def run(cmd: list[str], cwd: Path | None = None, ok_msg: str = "") -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True)
    if r.returncode != 0:
        fail(f"命令失败（{' '.join(str(c) for c in cmd[:3])}…）：\n{(r.stderr or r.stdout)[-800:]}")
    if ok_msg:
        print(ok_msg)
    return r


def probe(path: Path) -> dict:
    return json.loads(subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True).stdout)


def dur(path: Path) -> float:
    return float(probe(path)["format"]["duration"])


def clean_subtitle(text: str) -> str:
    out = []
    for i, ch in enumerate(text):
        if ch == ".":
            prev = text[i - 1] if i else ""
            nxt = text[i + 1] if i + 1 < len(text) else ""
            if prev.isdigit() and nxt.isdigit():
                out.append(ch)
            continue
        if ch in PUNCT:
            continue
        out.append(ch)
    return "".join(out).strip()


def ts_srt(x: float) -> str:
    ms = int(round(x * 1000)); h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def ts_ass(x: float) -> str:
    cs = int(round(x * 100)); h, cs = divmod(cs, 360000); m, cs = divmod(cs, 6000); s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def parse_srt(path: Path) -> list[tuple[str, float, float]]:
    """返回 [(text, start, end)]。"""
    cues = []
    blocks = re.split(r"\n\s*\n", path.read_text(encoding="utf-8-sig").strip())
    for b in blocks:
        lines = [l for l in b.splitlines() if l.strip()]
        if len(lines) < 2:
            continue
        m = re.search(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)", b)
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        st = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
        en = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
        text = "".join(lines[2:]) if len(lines) > 2 else ""
        cues.append((clean_subtitle(text), st, en))
    return cues


def pick_bgm(topic: str, script: str, bgm_dir: Path, explicit: str | None) -> Path:
    if explicit and explicit != "auto":
        p = Path(explicit)
        if not p.is_file():
            fail(f"指定的 BGM 不存在：{p}")
        return p
    hay = topic + script
    best, best_score = DEFAULT_BGM, -1
    for keys, name in BGM_RULES:
        score = sum(hay.count(k) for k in keys)
        if score > best_score:
            best, best_score = name, score
    cand = bgm_dir / f"{best}.mp3"
    if not cand.is_file():
        cand = bgm_dir / f"{DEFAULT_BGM}.mp3"
    if not cand.is_file():
        fail(f"未找到 BGM：{cand}（可用 --bgm 显式指定）")
    print(f"BGM 自动匹配 → {cand.name}（关键词得分 {best_score}）")
    return cand


def load_plan(p: Path) -> dict:
    if not p.is_file():
        fail(f"找不到 plan：{p}")
    return json.loads(p.read_text(encoding="utf-8"))


def out_dir(root: Path, plan: dict) -> Path:
    d = root / "outputs" / plan["topic"]
    d.mkdir(parents=True, exist_ok=True)
    return d


def plan_assets(root: Path, plan: dict) -> Path:
    d = out_dir(root, plan) / "assets"
    d.mkdir(parents=True, exist_ok=True)
    return d


def scratch_dir(root: Path, plan: dict) -> Path:
    d = root / "outputs" / "_scratch" / f"kefu_{plan.get('name', 'v1')}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def res_key(res: str) -> str:
    return res.replace("竖", "").replace("横", "")


def h3_price(res: str) -> float:
    return H3_PRICE.get(res_key(res), 0.06)


# ── 模式与台词工具 ──────────────────────────────────────────────────────
def mode_of(plan: dict) -> str:
    m = (plan.get("mode") or "native").lower()
    if m not in ("native", "dub"):
        fail(f"plan.mode 只能是 native / dub，当前 {m!r}")
    return m


def plan_lines(plan: dict) -> list[str]:
    """台词逐句（先套用 plan.spoken 读音替换，如 218 → 二幺八），保留标点供合成用。"""
    spoken = plan.get("spoken") or {}
    out = []
    for v in plan.get("voiceover", []):
        for k, r in spoken.items():
            v = v.replace(str(k), str(r))
        out.append(v)
    return out


def vol_stats(path: Path) -> tuple[float, float]:
    """(mean_volume, max_volume) dB；读不到返回 (-99, -99)。"""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
                       capture_output=True, text=True)
    txt = r.stderr or ""
    m = re.search(r"mean_volume:\s*(-?[\d.]+)", txt)
    x = re.search(r"max_volume:\s*(-?[\d.]+)", txt)
    return (float(m.group(1)) if m else -99.0, float(x.group(1)) if x else -99.0)


def has_audio(path: Path) -> bool:
    return any(s.get("codec_type") == "audio" for s in probe(path).get("streams", []))


# ── S2 · plan 模板 ───────────────────────────────────────────────────────
def cmd_plan(a) -> int:
    tpl = {
        "topic": "信息差福利模板_轮椅软广二创",
        "name": "偷偷客服_v1",
        "profile": "",
        "title": "标题（含关键词）",
        "platform": ["抖音", "视频号"],
        "mode": "native",
        "resolution": DEFAULT_RES,
        "duration": 10,
        "spoken": {"218": "二幺八"},
        "voice": DEFAULT_VOICE,
        "speed": DEFAULT_FINAL_SPEED,
        "bgm": "auto",
        "bgm_volume": DEFAULT_BGM_VOLUME,
        "persona_image": {
            "prompt": "竖版写实摄影，年轻女性客服……（人像提示词）",
            "size": DEFAULT_IMG_SIZE,
            "file": "客服_偷偷打电话.jpg",
        },
        "speech_prompt": "竖版写实摄影。年轻女性客服坐办公工位一角，身体微前倾、缩着肩，手机紧贴耳边、一手掩嘴侧压着声音悄悄说电话；神情认真不笑，嘴巴随台词自然开合、逐字清晰对口型；镜头稳定半身近景、人物居中；真实办公环境。",
        "lipsync_prompt": "（dub 链路）参考图中的客服……严格跟随音频对口型……画面内不出现任何文字、字幕、logo、水印。",
        "voiceover": ["第一句口播。", "第二句口播。"],
        "shots": [
            {"t": "0.0-3.0s", "scene": "画面描述", "vo": "第一句口播", "sub": "第一句口播"},
        ],
    }
    outp = Path(a.output)
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(tpl, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"模板已写 → {outp}（默认 native 直出：填好文案/分镜/人像提示词后跑 storyboard / image / direct / build；dub 旧链路改 mode 再跑 voice / lipsync）")
    return 0


# ── S1 · 分镜脚本（免费）─────────────────────────────────────────────────
def cmd_storyboard(a) -> int:
    root = find_root()
    plan = load_plan(Path(a.plan))
    out = out_dir(root, plan)
    name = plan.get("name", "v1")
    mode = mode_of(plan)
    total = plan.get("duration", DEFAULT_DURATION[mode])
    L = [f"# 分镜脚本 · 客服{'直出版' if mode == 'native' else '对口型版'}（{total} 秒）", ""]
    L += [f"- 画像：{plan.get('profile') or '（未指定）'} ｜ 平台：{'/'.join(plan.get('platform', []))} ｜ 画幅：{plan.get('resolution', DEFAULT_RES)}",
          f"- 标题：{plan.get('title', '')}", f"- 形式：客服模样的女孩**偷偷给家人打电话**，" +
          ("由 H3 直接生成**原生语音**说台词（不配音、无参考音色）" if mode == "native" else "直接对口型说台词（图+音频数字人对口型）"),
          "- 字幕：与技能 koubo 完全一致（微软雅黑 / 加粗 / 白字黑边 / 底部居中 / 去标点）", "", "## 分镜表", "",
          "| 镜 | 时间 | 画面 | 口播 | 字幕 |", "|----|------|------|------|------|"]
    for i, s in enumerate(plan.get("shots", []), 1):
        L.append(f"| {i} | {s.get('t', '')} | {s.get('scene', '')} | {s.get('vo', '')} | {s.get('sub', '')} |")
    L += ["", "## 口播（逐句）", ""]
    L += [f"{i}. {v}" for i, v in enumerate(plan.get("voiceover", []), 1)]
    prompt_hdr = "## H3 直出提示词（multi_image，原生语音）" if mode == "native" else "## H3 对口型提示词（image_audio）"
    prompt_txt = (plan.get("speech_prompt") or plan.get("lipsync_prompt", "")) if mode == "native" else plan.get("lipsync_prompt", "")
    L += ["", "## 参考图（人物形象）", "", f"> {plan.get('persona_image', {}).get('prompt', '')}", "",
          prompt_hdr, "", f"> {prompt_txt}", "",
          "## 技术参数", "",
          (f"- 出片：H3 multi_image 原生语音，{plan.get('resolution', DEFAULT_RES)}，单段 {total}s（无配音/无参考音色）" if mode == "native"
           else f"- 配音：{plan.get('voice', DEFAULT_VOICE)}；最终语速 {plan.get('speed', DEFAULT_FINAL_SPEED)}x"),
          ("- 字幕：对成片 ASR 对齐 → koubo 同款 ASS（微软雅黑 / 加粗 / 白字黑边 / 底部居中 / 去标点）" if mode == "native"
           else "- 字幕：koubo 同款 ASS（微软雅黑 / 加粗 / 白字黑边 / 底部居中 / 去标点）"),
          f"- 读音：{plan.get('spoken') or '数字按口语逐位（1→幺）'}",
          f"- BGM：{plan.get('bgm', 'auto')}，音量 {plan.get('bgm_volume', DEFAULT_BGM_VOLUME)}",
          (f"- 输出：outputs/{plan['topic']}/成片_{total}秒_客服直出_{name}.mp4" if mode == "native"
           else f"- 输出：outputs/{plan['topic']}/成片_{total}秒_客服对口型_{name}.mp4"), "",
          "## 成本预估", "",
          f"- 客服形象图 ≈ ￥{IMG_PRICE:.2f} ｜ H3 {res_key(plan.get('resolution', DEFAULT_RES))} = ￥{h3_price(plan.get('resolution', DEFAULT_RES)):.2f}/秒 × {total}s ≈ ￥{h3_price(plan.get('resolution', DEFAULT_RES)) * total:.2f} ｜ 合计 ≈ ￥{IMG_PRICE + h3_price(plan.get('resolution', DEFAULT_RES)) * total:.2f}", ""]
    doc = out / f"分镜脚本_{name}.md"
    doc.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"分镜脚本已写 → {doc}")
    return 0


# ── S3 · 客服形象图（计费）─────────────────────────────────────────────
def cmd_image(a) -> int:
    root = find_root()
    plan = load_plan(Path(a.plan))
    assets = plan_assets(root, plan)
    pi = plan.get("persona_image", {})
    if a.dry_run:
        print(f"[dry-run] 生图：1 张 · {pi.get('size', DEFAULT_IMG_SIZE)} · 预估 ≈ ￥{IMG_PRICE:.2f}（未发起）")
        return 0
    if not a.yes:
        fail(f"生图按量计费（预估 ≈ ￥{IMG_PRICE:.2f}）：确认后加 --yes，或先 --dry-run 看预估。", 3)
    before = {p.name for p in assets.glob("*.jpg")} | {p.name for p in assets.glob("*.png")}
    run([sys.executable, str(root / "skills/shared/scripts/ai_image.py"), "text2img",
         "--prompt", pi.get("prompt", ""), "--size", pi.get("size", DEFAULT_IMG_SIZE),
         "--n", "1", "--output", str(assets)])
    after = [p for p in assets.glob("*") if p.suffix.lower() in (".jpg", ".png", ".jpeg", ".webp")
             and p.name not in before]
    if not after:
        fail("生图后未在 assets 找到新图片")
    newest = max(after, key=lambda p: p.stat().st_mtime)
    target = assets / pi.get("file", "客服.jpg")
    if newest != target:
        shutil.copyfile(newest, target)
    print(f"✅ 客服形象图 → {target}")
    return 0


# ── S4 · 云配音 + 1.15x + 去标点字幕 ─────────────────────────────────────
def cmd_voice(a) -> int:
    root = find_root()
    plan = load_plan(Path(a.plan))
    out = out_dir(root, plan)
    name = plan.get("name", "v1")
    vo = plan.get("voiceover") or []
    if not vo:
        fail("plan 里没有 voiceover")
    voice = plan.get("voice", DEFAULT_VOICE)
    speed = float(plan.get("speed", DEFAULT_FINAL_SPEED))

    raw_txt = out / f"口播稿_{name}.txt"
    raw_txt.write_text("\n".join(vo) + "\n", encoding="utf-8")

    raw_mp3 = out / f"口播_{name}_raw.mp3"
    raw_srt = out / f"口播_{name}_raw.srt"
    run([sys.executable, str(root / "skills/shared/scripts/tts.py"), "speak",
         "--file", str(raw_txt), "-o", str(raw_mp3), "--subtitle", str(raw_srt),
         "-v", voice, "--engine", "closed"], ok_msg=f"云配音完成 → {raw_mp3.name}")

    out_mp3 = out / f"口播_{name}.mp3"
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(raw_mp3),
         "-filter:a", f"atempo={speed:.4f}", "-c:a", "libmp3lame", str(out_mp3)])

    # 字幕：时间轴按 1/speed 缩放 + 去标点
    cues = parse_srt(raw_srt)
    if not cues:
        fail("TTS 未产出可用字幕")
    lines = []
    for i, (txt, st, en) in enumerate(cues, 1):
        lines += [str(i), f"{ts_srt(st / speed)} --> {ts_srt(en / speed)}", txt, ""]
    (out / f"字幕_{name}.srt").write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    print(f"✅ 口播 {dur(out_mp3):.2f}s（{speed}x）→ 字幕_{name}.srt（{len(cues)} 条，去标点）")
    return 0


# ── S5 · H3 对口型（计费）──────────────────────────────────────────────
def cmd_lipsync(a) -> int:
    root = find_root()
    plan = load_plan(Path(a.plan))
    out = out_dir(root, plan)
    assets = plan_assets(root, plan)
    name = plan.get("name", "v1")
    res = plan.get("resolution", DEFAULT_RES)
    total = float(plan.get("duration", 15))
    img = assets / plan.get("persona_image", {}).get("file", "客服.jpg")
    aud = out / f"口播_{name}.mp3"
    if not img.is_file():
        fail(f"找不到人物参考图：{img}（先跑 image）")
    if not aud.is_file():
        fail(f"找不到配音：{aud}（先跑 voice）")
    if total > H3_MAX_AUDIO_SEC:
        fail(f"image_audio 单段上限 {H3_MAX_AUDIO_SEC}s，当前 {total}s，请分段")
    cost = h3_price(res) * total
    if a.dry_run:
        print(f"[dry-run] H3 对口型：{res} · {total}s → 预估 ≈ ￥{cost:.2f}（未发起）")
        return 0
    if not a.yes:
        fail(f"H3 按量计费（预估 ￥{cost:.2f}）：确认后加 --yes，或先 --dry-run 看预估。", 3)
    outp = assets / f"对口型_{name}.mp4"
    run([sys.executable, str(root / "skills/openclaw/autodl-h3-video/scripts/h3_video.py"),
         "-w", "image_audio", "-i", str(img), "-a", str(aud), "-r", res, "-d", str(int(total)),
         "-o", str(outp), "--prompt", plan.get("lipsync_prompt", "")],
        ok_msg=f"✅ 对口型 → {outp}（≈￥{cost:.2f}）")
    return 0


# ── S5n · H3 直出（原生语音，计费）─────────────────────────────────────
def cmd_direct(a) -> int:
    root = find_root()
    plan = load_plan(Path(a.plan))
    assets = plan_assets(root, plan)
    name = plan.get("name", "v1")
    res = plan.get("resolution", DEFAULT_RES)
    total = float(plan.get("duration", DEFAULT_DURATION["native"]))
    img = assets / plan.get("persona_image", {}).get("file", "客服.jpg")
    if not img.is_file():
        fail(f"找不到人物参考图：{img}（先跑 image）")
    if total > H3_MAX_VIDEO_SEC:
        fail(f"native 直出（multi_image）单段上限 {H3_MAX_VIDEO_SEC}s，当前 {total}s")
    lines = plan_lines(plan)
    prompt = (plan.get("speech_prompt") or plan.get("lipsync_prompt") or "").strip()
    if not prompt:
        fail("plan 缺少 speech_prompt")
    if lines:
        prompt = prompt.rstrip("。") + "。台词：「" + "，".join(l.strip("。！？!?") for l in lines) + "」"
    cost = h3_price(res) * total
    if a.dry_run:
        print(f"[dry-run] H3 直出（原生语音）：multi_image · {res} · {total}s → 预估 ≈ ￥{cost:.2f}（未发起）")
        return 0
    if not a.yes:
        fail(f"H3 按量计费（预估 ￥{cost:.2f}）：确认后加 --yes，或先 --dry-run。", 3)
    outp = assets / f"直出_{name}.mp4"
    run([sys.executable, str(root / "skills/openclaw/autodl-h3-video/scripts/h3_video.py"),
         "-w", "multi_image", "--prompt", prompt, "-i", str(img), "-r", res, "-d", str(int(total)),
         "-o", str(outp)], ok_msg=f"✅ 直出（原生语音）→ {outp}（≈￥{cost:.2f}）")
    return 0


# ── 字幕对齐（native：对成片 ASR 取真实时间轴）──────────────────────────
def _estimate_cues(video: Path, lines: list[str]) -> list[tuple[str, float, float]]:
    total = dur(video)
    n = sum(len(x) for x in lines) or 1
    acc, out = 0, []
    for ln in lines:
        s = acc / n * total
        acc += len(ln)
        out.append((ln, s, acc / n * total))
    return out


def _align_lines(raw: list[tuple[str, float, float]], lines: list[str]) -> list[tuple[str, float, float]]:
    if len(raw) == len(lines):
        return [(ln, s, e) for ln, (_, s, e) in zip(lines, raw)]
    out, i = [], 0
    for txt, st, en in raw:
        seg_chars = len(txt)
        take, acc = [], 0
        while i < len(lines) and (acc + len(lines[i]) <= seg_chars + 2 or not take):
            take.append(lines[i]); acc += len(lines[i]); i += 1
        span = en - st
        for k, ln in enumerate(take):
            base = sum(len(x) for x in take[:k])
            out.append((ln, st + span * (base / acc), st + span * ((base + len(ln)) / acc)))
    while i < len(lines):
        out.append((lines[i], raw[-1][2], raw[-1][2])); i += 1
    return out


def aligned_cues(root: Path, video: Path, lines: list[str], scratch: Path,
                 plan: dict) -> list[tuple[str, float, float]]:
    """native 字幕：优先 asr.py 对成片转写取真实时间轴，失败则按字数估时。"""
    if not lines:
        fail("plan.voiceover 为空")
    raw: list[tuple[str, float, float]] = []
    try:
        asr_srt = scratch / "asr_raw.srt"
        run([sys.executable, str(root / "skills/shared/scripts/asr.py"), "transcribe",
             "-i", str(video), "-o", str(asr_srt), "--language", "zh",
             "--model", plan.get("asr_model", "small")])
        raw = parse_srt(asr_srt)
    except SystemExit:
        print("⚠️ ASR 不可用，回退按字数估时")
    if not raw:
        raw = _estimate_cues(video, lines)
    return _align_lines(raw, lines)


# ── S6 · 字幕烧录 + BGM（免费后期）─────────────────────────────────────
def cmd_build(a) -> int:
    root = find_root()
    plan = load_plan(Path(a.plan))
    out = out_dir(root, plan)
    assets = plan_assets(root, plan)
    scratch = scratch_dir(root, plan)
    name = plan.get("name", "v1")
    mode = mode_of(plan)
    total = plan.get("duration", DEFAULT_DURATION[mode])

    video = assets / (f"直出_{name}.mp4" if mode == "native" else f"对口型_{name}.mp4")
    if not video.is_file():
        fail(f"找不到视频：{video}（native 先跑 direct；dub 先跑 lipsync）")
    srt = out / f"字幕_{name}.srt"
    if not srt.is_file():
        if mode == "native":
            cues = aligned_cues(root, video, [clean_subtitle(x) for x in plan_lines(plan)], scratch, plan)
            body = []
            for i, (t, s, e) in enumerate(cues, 1):
                body += [str(i), f"{ts_srt(s)} --> {ts_srt(e)}", t, ""]
            srt.write_text("\n".join(body) + "\n", encoding="utf-8-sig")
            print(f"字幕（ASR 对齐）→ {srt.name}（{len(cues)} 条）")
        else:
            fail(f"找不到字幕：{srt}（先跑 voice）")
    cues = parse_srt(srt)
    if not cues:
        fail("字幕为空")
    bad = [t for t, _, _ in cues if set(t) & set(PUNCT.replace(".", ""))]
    if bad:
        fail(f"字幕仍含标点：{bad}")

    st = [s for s in probe(video)["streams"] if s.get("codec_type") == "video"][0]
    W, H = int(st["width"]), int(st["height"])
    size = max(34, int(min(W, H) * 0.0625))
    head = ASS_HEAD.format(w=W, h=H, size=size, ml=int(W * 0.06), mr=int(W * 0.06), mv=int(H * 0.11))
    ev = "\n".join(f"Dialogue: 0,{ts_ass(x)},{ts_ass(y)},Sub,,0,0,0,,{t}" for t, x, y in cues)
    ass = scratch / "kefu_sub.ass"
    ass.write_text(head + ev + "\n", encoding="utf-8-sig")
    print(f"字幕 ASS 已写（去标点，{len(cues)} 条；字号={size}）")

    subbed = assets / f"对口型_{name}_subs.mp4"
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(video.resolve()),
         "-vf", f"ass={ass.name}", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
         "-c:a", "copy", str(subbed.resolve())], cwd=scratch, ok_msg=f"硬字幕烧录 → {subbed.name}")

    bgm = pick_bgm(plan.get("topic", "") + plan.get("title", ""), " ".join(plan.get("voiceover", [])),
                   Path(a.bgm_dir or DEFAULT_BGM_DIR), plan.get("bgm", "auto"))
    final = out / (f"成片_{total}秒_客服直出_{name}.mp4" if mode == "native"
                   else f"成片_{total}秒_客服对口型_{name}.mp4")
    run([sys.executable, str(root / "skills/shared/scripts/video_ops.py"), "bgm",
         "-i", str(subbed), "-o", str(final), "--music", str(bgm),
         "--music-volume", str(plan.get("bgm_volume", DEFAULT_BGM_VOLUME))],
        ok_msg=f"✅ 成片 → {final}")

    fd = dur(final)
    vst = [s for s in probe(final)["streams"] if s.get("codec_type") == "video"][0]
    ok_size = final.stat().st_size > 1_000_000
    ok_dur = abs(fd - float(total)) <= 2.0
    ok_res = abs(int(vst["width"]) / int(vst["height"]) - 9 / 16) < 0.02
    print(f"验收：时长={fd:.2f}s {'OK' if ok_dur else 'FAIL'} ｜ 画幅={vst['width']}x{vst['height']} {'OK' if ok_res else 'FAIL'} ｜ 大小={final.stat().st_size//1024}KB {'OK' if ok_size else 'FAIL'}")
    checks = [ok_size, ok_dur, ok_res]
    if mode == "native":
        mean, mx = vol_stats(final)
        ok_audio = has_audio(final) and mx > -35 and mean > -45
        print(f"验收：音轨（原生语音）mean={mean:.1f}dB max={mx:.1f}dB {'OK' if ok_audio else 'FAIL'}")
        checks.append(ok_audio)
    if not all(checks):
        fail("验收未通过，不交付")
    print("KEFU_OK")
    return 0


# ── 一键 ────────────────────────────────────────────────────────────────
def cmd_all(a) -> int:
    plan = load_plan(Path(a.plan))
    mode = mode_of(plan)
    steps = ("image", "direct", "build") if mode == "native" else ("image", "voice", "lipsync", "build")
    if a.dry_run:
        total = float(plan.get("duration", DEFAULT_DURATION[mode]))
        cost = IMG_PRICE + h3_price(plan.get("resolution", DEFAULT_RES)) * total
        print(f"[dry-run] 全链路预估 ≈ ￥{cost:.2f}（mode={mode}：生图 + H3；未发起）")
        return 0
    table = {"image": cmd_image, "voice": cmd_voice, "lipsync": cmd_lipsync,
             "direct": cmd_direct, "build": cmd_build}
    for step in steps:
        print(f"\n──── {step} ────")
        args = argparse.Namespace(plan=a.plan, yes=a.yes, dry_run=False, bgm_dir=a.bgm_dir)
        table[step](args)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="kefu · 客服数字人软广全链路：native（H3 直出原生语音，默认）/ dub（配音+对口型）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p0 = sub.add_parser("plan", help="输出链路配置模板 JSON")
    p0.add_argument("-o", "--output", required=True)
    p0.set_defaults(func=cmd_plan)

    p1 = sub.add_parser("storyboard", help="渲染分镜脚本 md（免费）")
    p1.add_argument("--plan", required=True)
    p1.set_defaults(func=cmd_storyboard)

    p2 = sub.add_parser("image", help="生成客服形象图（计费）")
    p2.add_argument("--plan", required=True)
    p2.add_argument("--dry-run", action="store_true")
    p2.add_argument("--yes", action="store_true")
    p2.set_defaults(func=cmd_image)

    p3 = sub.add_parser("voice", help="云配音 + 1.15x + 去标点字幕")
    p3.add_argument("--plan", required=True)
    p3.set_defaults(func=cmd_voice)

    p4 = sub.add_parser("lipsync", help="H3 image_audio 对口型（计费）")
    p4.add_argument("--plan", required=True)
    p4.add_argument("--dry-run", action="store_true")
    p4.add_argument("--yes", action="store_true")
    p4.set_defaults(func=cmd_lipsync)

    pd = sub.add_parser("direct", help="H3 multi_image 直出原生语音视频（计费；native 链路）")
    pd.add_argument("--plan", required=True)
    pd.add_argument("--dry-run", action="store_true")
    pd.add_argument("--yes", action="store_true")
    pd.set_defaults(func=cmd_direct)

    p5 = sub.add_parser("build", help="字幕烧录 + BGM → 成片（免费后期）")
    p5.add_argument("--plan", required=True)
    p5.add_argument("--bgm-dir", default=None)
    p5.set_defaults(func=cmd_build)

    p6 = sub.add_parser("all", help="全链路（生图+H3 计费，需 --yes）")
    p6.add_argument("--plan", required=True)
    p6.add_argument("--dry-run", action="store_true")
    p6.add_argument("--yes", action="store_true")
    p6.add_argument("--bgm-dir", default=None)
    p6.set_defaults(func=cmd_all)

    ns = ap.parse_args()
    return ns.func(ns)


if __name__ == "__main__":
    raise SystemExit(main())
