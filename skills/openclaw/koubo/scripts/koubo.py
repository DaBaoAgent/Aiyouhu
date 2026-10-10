#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""koubo.py — 口播成片一键封装：云配音 + 无标点字幕 + 自动匹配 BGM（原片不压缩）。

为什么是这套流程（踩过的坑）：
  · 云 TTS（CosyVoice2-0.5B 等小模型）同一句话多次合成，节奏会随机漂移：
    有时多出内部怪停顿（听感「磕磕巴巴」），有时末字发虚。
    → 对策：每句合成 N 条候选，剔除「有内部停顿」的，取时长最稳的一条。
  · 逐句 mp3 + atempo 再 concat，会在边界处引入杂音/吞字。
    → 对策：候选裁头尾静音后统一成 PCM(wav)，一次性 concat，最后只编码一次；
      语速不靠 TTS 加速（会被截尾），要加速也只在整轨上过一次 atempo。
  · TTS 直接传 speed>1 会截掉末字 → 合成一律 1.0，变速交给整轨 atempo。

固定约定（可用参数覆盖）：
  音色 FunAudioLLM/CosyVoice2-0.5B:claire · 最终语速 1.15x（整轨 atempo）· 句间停顿 0.25s
  字幕去标点（保留小数点）· 每句 6 条候选精选 · 尾部补静音防吞字 · BGM 自动匹配并去开头弱起
  满长不裁：旁白提前说完时，尾部留 BGM + 原画面空镜收尾（不裁原片）

用法（项目根运行）：
  python skills/openclaw/koubo/scripts/koubo.py build \
    --video outputs/主题/成片_15秒.mp4 --script outputs/主题/口播稿.txt \
    --topic 主题 --name 15秒_v8 --duration 15.65
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

DEFAULT_VOICE = "FunAudioLLM/CosyVoice2-0.5B:claire"
DEFAULT_SPEED = 1.15          # 最终语速（整轨 atempo；1.0=自然。本工作区偏好略快）
DEFAULT_TRIES = 6             # 每句合成候选数
DEFAULT_GAP = "0.25"          # 句间停顿（秒）；可传 "auto" 自动撑满目标时长
DEFAULT_BGM_VOLUME = 0.16
DEFAULT_BGM_DIR = r"D:\自动剪辑\BGM\抖音最火BGM"
DEFAULT_BGM = "一路都是风景"
DEFAULT_PAD = 0.10            # 每句尾部补静音（秒）
AUTO_GAP_RANGE = (0.15, 0.60)  # 句间停顿自动取值范围（秒）
PAUSE_DB = -35.0              # 内部停顿判定阈值
PAUSE_MIN = 0.20              # 内部停顿最短时长（秒）
PAUSE_EDGE = 0.12             # 距首尾多久内的静音不算「内部停顿」

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


def fail(msg: str, code: int = 1):
    print(f"错误：{msg}", file=sys.stderr)
    raise SystemExit(code)


def find_root() -> Path:
    here = Path(__file__).resolve()
    for p in [here, *here.parents]:
        if (p / "skills" / "shared" / "scripts" / "voice_clone.py").is_file():
            return p
    fail("找不到项目根（未定位到 skills/shared/scripts/voice_clone.py）")


def run(cmd: list[str], cwd: Path | None = None, ok_msg: str = "") -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True)
    if r.returncode != 0:
        fail(f"命令失败（{' '.join(str(c) for c in cmd[:3])}…）：\n{(r.stderr or r.stdout)[-700:]}")
    if ok_msg:
        print(ok_msg)
    return r


def probe(path: Path) -> dict:
    return json.loads(subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True).stdout)


def dur(path: Path) -> float:
    return float(probe(path)["format"]["duration"])


def silences(path: Path, noise_db: float = PAUSE_DB, min_dur: float = PAUSE_MIN) -> list[tuple[float, float]]:
    """返回静音段 [(start, end)]（秒）。"""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af",
                        f"silencedetect=noise={noise_db}dB:d={min_dur}", "-f", "null", "-"],
                       capture_output=True, text=True)
    txt = r.stderr
    starts = [float(x) for x in re.findall(r"silence_start:\s*([0-9.]+)", txt)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*([0-9.]+)", txt)]
    return list(zip(starts, ends))


def trim_bounds(path: Path, total: float) -> tuple[float, float]:
    """探测首尾静音，返回应保留的 [lead, trail] 秒。"""
    sil = silences(path, -45.0, 0.08)
    lead, trail = 0.0, total
    if sil and sil[0][0] <= 0.06:
        lead = sil[0][1]
    if sil and sil[-1][1] >= total - 0.06:
        trail = sil[-1][0]
    if trail - lead < 0.15:
        return 0.0, total
    return lead, trail


def leading_quiet(path: Path, cap: float = 2.5, rel_db: float = -6.0) -> float:
    """探测 BGM 开头的静音/弱起，返回建议裁掉的秒数。"""
    import array
    import math
    raw = subprocess.run(["ffmpeg", "-v", "quiet", "-i", str(path), "-t", "20",
                          "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                         capture_output=True).stdout
    if not raw:
        return 0.0
    samples = array.array("h")
    samples.frombytes(raw)
    win = 800
    rms = []
    for i in range(0, len(samples) - win, win):
        chunk = samples[i:i + win]
        rms.append(math.sqrt(sum(float(x) * x for x in chunk) / len(chunk)))
    if len(rms) < 4:
        return 0.0
    ref = sorted(rms)[len(rms) // 2]
    if ref <= 0:
        return 0.0
    thresh = ref * (10 ** (rel_db / 20))
    for i, v in enumerate(rms):
        if v >= thresh:
            t = i * win / 16000
            return round(min(t, cap), 3) if t > 0.1 else 0.0
    return 0.0


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


def ts_srt(x: float) -> str:
    ms = int(round(x * 1000)); h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def ts_ass(x: float) -> str:
    cs = int(round(x * 100)); h, cs = divmod(cs, 360000); m, cs = divmod(cs, 6000); s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


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


def synth_candidates(root: Path, scratch: Path, env_file: Path, provider: str,
                     voice_id: str, i: int, line: str, tries: int, reuse: bool) -> list[Path]:
    """合成第 i 句的 tries 条候选，返回可用的候选路径。"""
    cands = []
    for k in range(tries):
        p = scratch / f"line{i}_try{k}.mp3"
        if reuse and p.is_file() and p.stat().st_size > 0:
            pass
        else:
            r = subprocess.run(
                [sys.executable, str(root / "skills/shared/scripts/voice_clone.py"), "clone",
                 "--provider", provider, "--env-file", str(env_file), "--voice-id", voice_id,
                 "--speed", "1.0", "--text", line, "-o", str(p)],
                capture_output=True, text=True, cwd=str(root))
            if r.returncode != 0:
                print(f"    try{k} 失败：{(r.stderr or r.stdout).strip()[-160:]}")
                continue
        if p.is_file() and p.stat().st_size > 0:
            cands.append(p)
    return cands


def pick_candidate(cands: list[Path]) -> tuple[Path, float, int, int]:
    """从候选中挑最稳的一条：先剔除有内部停顿的，再取时长中位数附近者。
    返回 (path, 原时长, 干净候选数, 总候选数)。"""
    scored = []
    for p in cands:
        d = dur(p)
        sil = silences(p, PAUSE_DB, PAUSE_MIN)
        inner = [(s, e) for (s, e) in sil if s > PAUSE_EDGE and e < d - PAUSE_EDGE]
        scored.append({"p": p, "d": d, "inner": inner, "pause": sum(e - s for s, e in inner)})
    clean = [c for c in scored if not c["inner"]]
    pool = clean or sorted(scored, key=lambda c: c["pause"])[:max(1, len(scored) // 2)]
    ds = sorted(c["d"] for c in pool)
    med = ds[len(ds) // 2]
    best = min(pool, key=lambda c: abs(c["d"] - med))
    return best["p"], best["d"], len(clean), len(scored)


def build(a) -> int:
    root = find_root()
    plan = load_plan(Path(a.plan)) if getattr(a, "plan", None) else None
    if plan:
        a.topic = getattr(a, "topic", None) or plan.get("topic")
        a.name = getattr(a, "name", None) or plan.get("name") or "成片"
        if a.duration is None:
            a.duration = plan.get("duration")
    if not a.topic:
        fail("缺 --topic（或用 --plan 提供）")
    if not a.name:
        fail("缺 --name（或用 --plan 提供）")
    env_file = root / ".env"
    out_dir = root / "outputs" / a.topic
    if not out_dir.is_dir():
        fail(f"主题目录不存在：{out_dir}")
    if not a.script:
        vo = (plan or {}).get("voiceover") or []
        if not vo:
            fail("缺 --script，且 --plan 里没有 voiceover")
        sp = out_dir / f"口播稿_{a.name}.txt"
        sp.write_text("\n".join(vo) + "\n", encoding="utf-8")
        a.script = str(sp)
    if not a.video:
        if not plan:
            fail("缺 --video（或用 --plan 提供 segments 以推算源片）")
        a.video = str(plan_source_video(root, plan))
    lines = [l.strip() for l in Path(a.script).read_text(encoding="utf-8-sig").splitlines() if l.strip()]
    if not lines:
        fail("脚本文件为空")
    video = Path(a.video)
    video = video if video.is_absolute() else (root / video)
    if not video.is_file():
        fail(f"视频不存在：{video}")
    scratch = root / "outputs" / "_scratch" / f"koubo_{a.name}"
    scratch.mkdir(parents=True, exist_ok=True)

    voice_id = a.voice or os.environ.get("VOICE_NARRATOR_VOICE_ID", "") or DEFAULT_VOICE
    speed = float(a.speed if a.speed is not None else DEFAULT_SPEED)
    tries = max(1, int(a.tries))
    print(f"音色={voice_id}  自然语速合成(1.0)  每句候选={tries}  句数={len(lines)}")

    # 1) 逐句多候选合成 + 精选（剔除内部怪停顿）
    parts: list[tuple[Path, float]] = []
    for i, line in enumerate(lines):
        cands = synth_candidates(root, scratch, env_file, a.provider, voice_id, i, line, tries, a.reuse_parts)
        if not cands:
            fail(f"第 {i} 句合成失败（无可用候选）：{line}")
        best, bd, nclean, ntot = pick_candidate(cands)
        lead, trail = trim_bounds(best, bd)
        wav = scratch / f"line{i}_clean.wav"
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-ss", f"{lead:.3f}", "-to", f"{trail:.3f}", "-i", str(best),
             "-ar", "44100", "-ac", "1", "-c:a", "pcm_s16le", str(wav)])
        td = dur(wav)
        parts.append((wav, td))
        print(f"  [{i}] 候选 {ntot} 条（干净 {nclean}）→ 选 {bd:.2f}s，裁剪后 {td:.2f}s :: {line}")

    voice_total = sum(td for _, td in parts)
    n = len(lines)
    print(f"纯口播(自然语速)={voice_total:.2f}s")

    video_len = dur(video)
    target = a.duration if a.duration else video_len
    pad = a.pad

    # 2) 句间停顿：自然语速下自动撑满目标时长；塞不下再对整轨 atempo
    atempo = 1.0
    if a.gap == "auto":
        gap = (target - voice_total - n * pad) / (n - 1) if n > 1 else 0.0
        if gap > AUTO_GAP_RANGE[1]:
            gap = AUTO_GAP_RANGE[1]           # 音频短了：靠尾部定格补足
        elif gap < AUTO_GAP_RANGE[0]:
            gap = AUTO_GAP_RANGE[0]           # 音频长了：整轨提速
            room = target - n * pad - (n - 1) * gap
            if 0.2 < room < voice_total:
                atempo = voice_total / room
    else:
        gap = float(a.gap)
    if abs(speed - 1.0) > 0.001:              # 显式语速优先
        atempo = speed
    expect = voice_total / atempo + n * pad + (n - 1) * gap
    print(f"句间停顿={gap:.2f}s  尾部补静音={pad:.2f}s  整轨 atempo={atempo:.3f}  → 音轨预计 {expect:.2f}s")
    if target and expect > target + 0.05:
        fail(f"口播+停顿({expect:.2f}s) 超过目标 {target:.2f}s，请精简文案")
    print(f"视频原长={video_len:.2f}s  目标成片={target:.2f}s（不压缩原片）")

    # 3) 干净拼接：PCM 一次性 concat（无逐句 mp3 边界），再整轨变速一次
    inputs: list[str] = []
    filt: list[str] = []
    seq: list[str] = []
    for p, _ in parts:
        inputs += ["-i", str(p)]
    for i in range(n):
        filt.append(f"[{i}:a]apad=pad_dur={pad:.3f}[a{i}]")
        seq.append(f"[a{i}]")
        if i < n - 1:
            filt.append(f"anullsrc=r=44100:cl=mono:d={gap:.3f}[g{i}]")
            seq.append(f"[g{i}]")
    filt.append(f"{''.join(seq)}concat=n={len(seq)}:v=0:a=1[voice]")
    last = "[voice]"
    if abs(atempo - 1.0) > 0.001:
        filt.append(f"[voice]atempo={atempo:.4f}[voiceS]")
        last = "[voiceS]"
    voice_mp3 = out_dir / f"口播_{a.name}.mp3"
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *inputs,
         "-filter_complex", ";".join(filt), "-map", last, "-c:a", "libmp3lame", str(voice_mp3)],
        cwd=scratch)
    voice_len = dur(voice_mp3)
    print(f"口播音轨={voice_len:.2f}s")

    # 4) 字幕（去标点）
    cues, t = [], 0.0
    for (p, td), s in zip(parts, lines):
        d = td / atempo
        cues.append((clean_subtitle(s) if not a.keep_punct else s.strip(), t, t + d))
        t += d + pad + gap
    bad = [c[0] for c in cues if set(c[0]) & set(PUNCT.replace(".", ""))]
    if bad:
        fail(f"字幕仍含标点：{bad}")

    st = [s for s in probe(video)["streams"] if s.get("codec_type") == "video"][0]
    W, H = int(st["width"]), int(st["height"])
    size = max(34, int(min(W, H) * 0.0625))
    head = ASS_HEAD.format(w=W, h=H, size=size, ml=int(W * 0.06), mr=int(W * 0.06), mv=int(H * 0.11))
    ev = "\n".join(f"Dialogue: 0,{ts_ass(x)},{ts_ass(y)},Sub,,0,0,0,,{s}" for s, x, y in cues)
    (out_dir / f"字幕_{a.name}.ass").write_text(head + ev + "\n", encoding="utf-8-sig")
    (out_dir / f"口播_{a.name}.srt").write_text(
        "\n".join(f"{i}\n{ts_srt(x)} --> {ts_srt(y)}\n{s}\n" for i, (s, x, y) in enumerate(cues, 1)),
        encoding="utf-8-sig")
    (out_dir / f"口播稿_{a.name}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"字幕已写（去标点，{len(cues)} 条）")

    # 5) BGM：去开头弱起 → 混音（旁白补静音到目标时长，BGM 才能铺满）
    bgm_raw = pick_bgm(a.topic, "\n".join(lines), Path(a.bgm_dir), a.bgm)
    bgm = bgm_raw
    if a.bgm_trim:
        ls = leading_quiet(bgm_raw)
        if ls > 0.05:
            bgm = scratch / "bgm_trim.mp3"
            run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{ls:.3f}",
                 "-i", str(bgm_raw), "-af", "afade=t=in:st=0:d=0.12",
                 "-c:a", "libmp3lame", str(bgm)])
            print(f"BGM 裁掉开头弱起/静音：{ls:.2f}s")
        else:
            print("BGM 开头无弱起，直接使用")
    mix_voice = voice_mp3
    if target > voice_len + 0.01:
        mix_voice = scratch / "voice_pad.mp3"
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(voice_mp3),
             "-af", "apad", "-t", f"{target:.3f}", "-c:a", "libmp3lame", str(mix_voice)])
    mixed = out_dir / f"口播BGM_{a.name}.mp3"
    run([sys.executable, str(root / "skills/shared/scripts/audio_mix.py"), "mix",
         "--voice", str(mix_voice), "--bgm", str(bgm),
         "--bgm-volume", str(a.bgm_volume), "-o", str(mixed)],
        cwd=root, ok_msg=f"混音完成 → {mixed.name}")
    mixed_len = dur(mixed)

    # 6) 渲染（原片满长：不够则末帧定格补足，绝不压缩）
    sub_copy = scratch / "koubo_sub.ass"
    shutil.copyfile(out_dir / f"字幕_{a.name}.ass", sub_copy)
    pad_v = max(0.0, target - video_len)
    vf = f"[0:v]tpad=stop_mode=clone:stop_duration={pad_v:.3f},ass=koubo_sub.ass[v]" if pad_v > 0.01 \
        else "[0:v]ass=koubo_sub.ass[v]"
    final = (root / a.final) if a.final else (out_dir / f"成片_{a.name}.mp4")
    final = final if final.is_absolute() else (root / final)
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(video), "-i", str(mixed),
         "-filter_complex", vf, "-map", "[v]", "-map", "1:a",
         "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-t", f"{target:.3f}", str(final)], cwd=scratch)

    # 7) 验收
    info = probe(final)
    fdur = float(info["format"]["duration"])
    vs = [s for s in info["streams"] if s.get("codec_type") == "video"][0]
    aud = [s for s in info["streams"] if s.get("codec_type") == "audio"]
    checks = {
        "时长≈目标": abs(fdur - target) <= 0.15,
        "不短于原片": fdur >= video_len - 0.05,
        "口播全部容纳": fdur >= voice_len - 0.05,
        "含句间停顿": gap >= 0.1,
        "分辨率一致": (int(vs["width"]), int(vs["height"])) == (W, H),
        "有音轨": bool(aud),
        "混音轨铺满": abs(mixed_len - target) <= 0.25,
    }
    print("\n验收：")
    for k, v in checks.items():
        print(f"  {'✅' if v else '❌'} {k}")
    print(json.dumps({"final": str(final), "duration": round(fdur, 3),
                      "size_bytes": final.stat().st_size, "voice_sec": round(voice_total, 2),
                      "gap_sec": round(gap, 2), "atempo": round(atempo, 3), "bgm": bgm_raw.name,
                      "subtitle_lines": len(cues)}, ensure_ascii=False, indent=2))
    if not all(checks.values()):
        fail("验收未全部通过，不交付", 2)
    print("KOUBO_OK")
    return 0


# ────────────────── 全链路：文案 → H3 提示词 → 两段生成拼接 → 配音字幕BGM ──────────────────

H3_SIX = ("参考主体", "镜头景别", "主体动作", "场景环境", "光线风格", "画质约束")
H3_PRICE = {"480p": 0.04, "768p": 0.06, "1080p": 0.10}   # ¥/秒
H3_MAX_SEG = 10                                            # H3 单段上限（秒）
# 折展切换：折叠↔展开任一方向的动作词（排除「折叠态/展开态/折叠后」等静态/回指）
STATE_FLIP_RE = re.compile(r"(折叠(?!态|后|好)|展开(?!态|后)|折成|收拢|收好|收起|折起)")
STATE_FLIP_RULE = "折叠与展开状态切换全程 0.3 秒内一气呵成"   # 两方向通用（2026-10-09 用户定）


def _with_state_flip(text: str) -> str:
    """含折展切换的「主体动作」自动补写 0.3 秒约束；已写明（含 0.3）则不重复。"""
    t = str(text or "").strip().rstrip("。；，、,;. ")
    if not t or "0.3" in t:
        return t
    if STATE_FLIP_RE.search(t):
        return f"{t}，{STATE_FLIP_RULE}"
    return t


def _seg_prompt(seg: dict) -> dict:
    """返回段提示词的副本，并对「主体动作」应用状态切换 0.3 秒约束。"""
    pr = dict(seg.get("prompt") or {})
    if pr.get("主体动作"):
        pr["主体动作"] = _with_state_flip(pr["主体动作"])
    return pr


def _slug(text: str, n: int = 8) -> str:
    keep = "".join(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", text))
    return keep[:n] or "clip"


def load_plan(path: Path) -> dict:
    if not path.is_file():
        fail(f"找不到 plan 文件：{path}")
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as e:
        fail(f"plan 不是合法 JSON：{e}")


def h3_prompt_line(seg: dict) -> str:
    """把六段式字段拼成单行提示词；含破折号直接拦（H3 会丢弃整句）。
    含「折叠 ↔ 展开」切换的段会自动补写「0.3 秒内一气呵成」（两个方向都适用）。"""
    pr = _seg_prompt(seg)
    fields = []
    for k in H3_SIX:
        v = str(pr.get(k, "")).strip().rstrip("。；，,;. ")
        if v:
            fields.append(f"{k}：{v}")
    line = "；".join(fields) + "。"
    if "——" in line:
        fail(f"第 {seg.get('id', '?')} 段提示词含破折号「——」，H3 会丢弃整句，请改为分号/逗号")
    if not fields:
        fail(f"第 {seg.get('id', '?')} 段没有六段式提示词（prompt 六字段）")
    return " ".join(line.split())


def plan_segments(plan: dict) -> list[dict]:
    segs = plan.get("segments") or []
    if not segs:
        fail("plan.segments 为空")
    for s in segs:
        d = int(s.get("duration", 0))
        if not (1 <= d <= H3_MAX_SEG):
            fail(f"第 {s.get('id', '?')} 段 {d}s 超出 H3 单段 1–{H3_MAX_SEG}s（建议每段 4s，如 12s 拆 3 段）")
    return segs


def plan_total(plan: dict) -> int:
    return sum(int(s["duration"]) for s in plan_segments(plan))


def plan_out_dir(root: Path, plan: dict) -> Path:
    d = root / "outputs" / str(plan["topic"])
    d.mkdir(parents=True, exist_ok=True)
    return d


def plan_assets(root: Path, plan: dict) -> Path:
    d = plan_out_dir(root, plan) / "assets"
    d.mkdir(parents=True, exist_ok=True)
    return d


def plan_source_video(root: Path, plan: dict) -> Path:
    return plan_out_dir(root, plan) / f"成片_{plan_total(plan)}秒.mp4"


def h3_price(res: str) -> float:
    return H3_PRICE.get(res.replace("竖", "").replace("横", ""), 0.06)


def write_h3_doc(root: Path, plan: dict) -> Path:
    out = plan_out_dir(root, plan)
    segs = plan_segments(plan)
    res = plan.get("resolution", "768p竖")
    total = plan_total(plan)
    name = plan.get("name", "成片")
    L = [f"# H3 视频提示词（{total} 秒）· {plan.get('title', plan['topic'])}", ""]
    for k, v in (("画像", plan.get("profile", "—")), ("热点", plan.get("hot_topic", "—")),
                 ("工作流", plan.get("workflow", "multi_image")), ("画幅", res),
                 ("脚本来源", f"文案分镜（{name}）")):
        L.append(f"- {k}：{v}")
    L += ["", "## ⚠️ 单段上限 10s，分段生成后拼接",
          f"H3 视频工作流单次时长上限 {H3_MAX_SEG}s；本片 {total}s 拆为 "
          + " + ".join(str(int(s["duration"])) for s in segs) + " 段，生成后用 "
          + "`skills/shared/scripts/video_ops.py concat` 拼接。",
          "", "参考图（放 `assets/`）：", ""]
    cmds = []
    for s in segs:
        L += [f"### Clip {s.get('id', '?')}｜{s.get('shots', '')}｜{int(s['duration'])}s", "",
              "**六段式提示词**", ""]
        pr = _seg_prompt(s)
        for i, k in enumerate(H3_SIX, 1):
            L.append(f"{i}. **{k}**：{str(pr.get(k, '')).strip()}")
        L += ["", f"**参考图**：{', '.join(s.get('refs', [])) or '—'}",
              f"**对应口播（后期配音，不进提示词）**：{s.get('voiceover', '—')}", ""]
        refs = " ".join(f"-i outputs/{plan['topic']}/assets/{r}" for r in s.get("refs", []))
        cmds.append(
            f"# Clip {s.get('id', '?')}（{int(s['duration'])}s）\n"
            f"python skills/openclaw/autodl-h3-video/scripts/h3_video.py -w {plan.get('workflow', 'multi_image')} \\\n"
            f"  --prompt {json.dumps(h3_prompt_line(s), ensure_ascii=False)} \\\n"
            f"  {refs} -r {res} -d {int(s['duration'])} \\\n"
            f"  -o outputs/{plan['topic']}/assets/clip{s.get('id', '?')}_{_slug(s.get('shots', ''))}.mp4\n")
    concat = "python skills/shared/scripts/video_ops.py concat " + " ".join(
        f"-i outputs/{plan['topic']}/assets/clip{s.get('id', '?')}_{_slug(s.get('shots', ''))}.mp4" for s in segs) \
        + f" -o outputs/{plan['topic']}/成片_{total}秒.mp4"
    L += ["## 运行命令", "", "```bash", *cmds, concat, "```", "",
          f"## 成本预估：{res} = ¥{h3_price(res):.2f}/秒 → {total}s ≈ **¥{h3_price(res) * total:.2f}**（未发起，先确认）", "",
          "## 自检要点", "",
          f"- [ ] 拼接后总时长 {total}s±1s、竖屏 9:16、文件 >1MB（脚本内置 ffprobe 验收）",
          "- [ ] 人物与产品跨段一致（同车型、同配色），不一致带意见重跑一次",
          "- [ ] 提示词无破折号「——」、无电子文字/字幕描述",
          "- [ ] 折展段「主体动作」写明状态起止 + 折叠↔展开任一方向均「0.3 秒内一气呵成」",
          "- [ ] 折展/移动场景已给两张参考图（展开态+折叠态 / 45°+侧面）",
          "- [ ] 合规：无医疗宣称、无「最/第一/100%」绝对化用语、不演示危险场景，老人场景含安全提示", ""]
    doc = out / f"H3视频提示词_{name}.md"
    doc.write_text("\n".join(L), encoding="utf-8")
    return doc


def _seg_output(assets: Path, s: dict) -> Path:
    return assets / f"clip{s.get('id', '?')}_{_slug(s.get('shots', ''))}.mp4"


def _run_h3gen(root: Path, plan: dict, dry_run: bool, yes: bool,
               only: set[int] | None = None, skip_existing: bool = False,
               fit: bool = False) -> Path:
    """生成各分段并拼接。--only 只跑指定段；--skip-existing 跳过已有段；--fit 拼接前把每段裁到目标秒数。"""
    segs = plan_segments(plan)
    res = plan.get("resolution", "768p竖")
    total = plan_total(plan)
    assets = plan_assets(root, plan)
    todo = []
    for s in segs:
        out = _seg_output(assets, s)
        if only and int(s.get("id", 0)) not in only:
            continue
        if skip_existing and out.is_file() and out.stat().st_size > 0:
            continue
        todo.append(s)
    cost = h3_price(res) * sum(int(s["duration"]) for s in todo)
    picked = "、".join(str(s.get("id", "?")) for s in todo) or "无"
    print(f"H3 分段：{len(segs)} 段 / 共 {total}s / {res} → 本次生成 {len(todo)} 段（{picked}）预估约 ¥{cost:.2f}")
    if dry_run:
        for s in todo:
            print(f"  · Clip {s.get('id', '?')} {int(s['duration'])}s")
        print("--dry-run：未提交。确认后加 --yes 真正生成。")
        return plan_source_video(root, plan)
    if todo and not yes:
        fail(f"H3 按量计费（预估 ¥{cost:.2f}）：确认后加 --yes 再跑，或先 --dry-run 看预估。", 3)
    h3 = root / "skills/openclaw/autodl-h3-video/scripts/h3_video.py"
    if not h3.is_file():
        fail(f"找不到 H3 脚本：{h3}")
    for s in todo:
        refs: list[str] = []
        for r in s.get("refs", []):
            p = Path(r)
            if not p.is_absolute():
                cand = assets / r
                p = cand if cand.is_file() else (root / r)
            if not p.is_file():
                fail(f"参考图不存在：{r}")
            refs += ["-i", str(p)]
        out = _seg_output(assets, s)
        out.unlink(missing_ok=True)                      # 重跑该段：清掉旧文件与状态，确保真正重新生成
        Path(str(out) + ".state.json").unlink(missing_ok=True)
        print(f"→ Clip {s.get('id', '?')} {int(s['duration'])}s …")
        run([sys.executable, str(h3), "-w", plan.get("workflow", "multi_image"),
             "--prompt", h3_prompt_line(s), *refs, "-r", res, "-d", str(int(s["duration"])),
             "-o", str(out)], cwd=root)
    clips = [_seg_output(assets, s) for s in segs]
    if fit:
        for s, c in zip(segs, clips):
            want = int(s["duration"])
            if c.is_file() and dur(c) > want + 0.05:
                tmp = c.with_suffix(".fit.mp4")
                run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(c),
                     "-t", str(want), "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-an", str(tmp)],
                    cwd=root)
                tmp.replace(c)
                print(f"  · Clip {s.get('id', '?')} 裁到 {want}s（原 {dur(c):.2f}s）")
    missing = [c.name for c in clips if not c.is_file() or c.stat().st_size == 0]
    if missing:
        fail(f"拼接前缺少分段文件：{'、'.join(missing)}（用 --only N 补跑该段）")
    src = plan_source_video(root, plan)
    if len(clips) == 1:
        shutil.copyfile(clips[0], src)
    else:
        run([sys.executable, str(root / "skills/shared/scripts/video_ops.py"), "concat",
             "-i", *[str(c) for c in clips], "-o", str(src)],
            cwd=root, ok_msg=f"分段拼接完成 → {src.name}")
    return src


def cmd_plan_template(a) -> int:
    tpl = {
        "topic": "主题目录名（outputs/<topic>/）",
        "name": "15秒_v1",
        "profile": "画像名（可留空）",
        "hot_topic": "热点或选题",
        "title": "标题（含热点关键词）",
        "platform": ["抖音", "视频号"],
        "workflow": "multi_image",
        "resolution": "768p竖",
        "duration": 12.0,
        "copy": {"titles": ["备选1", "备选2"], "body": "视频配文", "cta": ["行动引导"],
                 "tags": ["#话题"]},
        "voiceover": ["口播第 1 句。", "口播第 2 句。"],
        "segments": [
            {"id": 1, "duration": 4, "shots": "痛点引入 + 产品出场",
             "refs": ["展开态.png"],
             "prompt": {k: "" for k in H3_SIX},
             "voiceover": "本段对应口播"},
            {"id": 2, "duration": 4, "shots": "三步折叠演示",
             "refs": ["展开态.png", "折叠态.png"],
             "prompt": {k: "" for k in H3_SIX},
             "voiceover": "本段对应口播"},
            {"id": 3, "duration": 4, "shots": "折叠态对比 + 收尾",
             "refs": ["折叠态.png"],
             "prompt": {k: "" for k in H3_SIX},
             "voiceover": "本段对应口播"},
        ],
    }
    out = Path(a.out)
    out.write_text(json.dumps(tpl, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"模板已写 → {out}（填好文案/分镜/六段式提示词后跑 h3plan）")
    return 0


def cmd_h3plan(a) -> int:
    root = find_root()
    plan = load_plan(Path(a.plan))
    doc = write_h3_doc(root, plan)
    print(f"H3 提示词文档已写 → {doc}")
    print(f"预估视频成本：{plan.get('resolution', '768p竖')} × {plan_total(plan)}s "
          f"≈ ¥{h3_price(plan.get('resolution', '768p竖')) * plan_total(plan):.2f}（未发起）")
    return 0


def cmd_h3gen(a) -> int:
    only = {int(x) for x in str(a.only).split(",")} if getattr(a, "only", None) else None
    _run_h3gen(find_root(), load_plan(Path(a.plan)), a.dry_run, a.yes, only,
               getattr(a, "skip_existing", False), getattr(a, "fit", False))
    return 0


def cmd_all(a) -> int:
    root = find_root()
    plan = load_plan(Path(a.plan))
    write_h3_doc(root, plan)
    only = {int(x) for x in str(a.only).split(",")} if getattr(a, "only", None) else None
    _run_h3gen(root, plan, a.dry_run, a.yes, only, getattr(a, "skip_existing", False),
               getattr(a, "fit", False))
    if a.dry_run:
        print("--dry-run：H3 与后期均未执行。")
        return 0
    ns = argparse.Namespace(
        plan=str(a.plan), video=None, script=None, topic=None, name=None,
        duration=plan.get("duration"), gap=DEFAULT_GAP, pad=DEFAULT_PAD, tries=a.tries,
        voice=None, speed=None, provider=os.environ.get("VOICE_PROVIDER", "openai-compatible"),
        bgm="auto", bgm_dir=DEFAULT_BGM_DIR, bgm_volume=DEFAULT_BGM_VOLUME, bgm_trim=True,
        keep_punct=False, reuse_parts=a.reuse_parts, final=None)
    return build(ns)


def main() -> int:
    ap = argparse.ArgumentParser(description="koubo · 口播广告全链路：文案 → H3 提示词 → 两段生成拼接 → 配音字幕BGM")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="配音 + 无标点字幕 + BGM → 成片（不压缩原片）")
    b.add_argument("--video", default=None, help="原片（不压缩，保持满长）；可省略，由 --plan 推算")
    b.add_argument("--script", default=None, help="口播稿 txt（一行一句）；可省略，用 --plan.voiceover")
    b.add_argument("--topic", default=None, help="主题目录名（outputs/<topic>/）")
    b.add_argument("--plan", default=None, help="链路配置 JSON（缺失项由它补全）")
    b.add_argument("--name", default=None, help="产物后缀名")
    b.add_argument("--duration", type=float, default=None, help="目标成片秒数（默认=原片长度）")
    b.add_argument("--gap", default=DEFAULT_GAP, help=f"句间停顿秒数或 auto（默认 {DEFAULT_GAP}s；auto=自动撑满目标时长）")
    b.add_argument("--pad", type=float, default=DEFAULT_PAD, help=f"每句尾部补静音秒数（默认 {DEFAULT_PAD}）")
    b.add_argument("--tries", type=int, default=DEFAULT_TRIES, help=f"每句合成候选数（默认 {DEFAULT_TRIES}）")
    b.add_argument("--voice", default=None, help=f"云音色 voice-id（默认 {DEFAULT_VOICE}）")
    b.add_argument("--speed", type=float, default=None, help=f"最终语速（默认 {DEFAULT_SPEED}；>1 走整轨 atempo）")
    b.add_argument("--provider", default=os.environ.get("VOICE_PROVIDER", "openai-compatible"))
    b.add_argument("--bgm", default="auto", help="auto 或 BGM 文件路径")
    b.add_argument("--bgm-dir", default=DEFAULT_BGM_DIR)
    b.add_argument("--bgm-volume", type=float, default=DEFAULT_BGM_VOLUME)
    b.add_argument("--no-bgm-trim", dest="bgm_trim", action="store_false", help="不去 BGM 开头静音")
    b.add_argument("--keep-punct", action="store_true", help="保留字幕标点（默认去掉）")
    b.add_argument("--reuse-parts", action="store_true", help="复用 _scratch 里已有的候选音频")
    b.add_argument("--final", default=None, help="最终视频路径（默认 outputs/<topic>/成片_<name>.mp4）")
    b.set_defaults(func=build, bgm_trim=True)

    pt = sub.add_parser("plan-template", help="输出链路配置模板 JSON")
    pt.add_argument("-o", "--out", default="koubo_plan.json")
    pt.set_defaults(func=cmd_plan_template)

    hp = sub.add_parser("h3plan", help="生成两段式 H3 提示词文档 + 运行命令（不调 H3、不花钱）")
    hp.add_argument("--plan", required=True)
    hp.set_defaults(func=cmd_h3plan)

    hg = sub.add_parser("h3gen", help="调 H3 生成各分段并拼接为原片（按量计费）")
    hg.add_argument("--plan", required=True)
    hg.add_argument("--dry-run", action="store_true", help="只打印预估费用，不提交")
    hg.add_argument("--yes", action="store_true", help="确认付费并执行")
    hg.add_argument("--only", default=None, help="只生成这些段（逗号分隔，如 2 或 1,3），用于单段重跑")
    hg.add_argument("--skip-existing", action="store_true", help="跳过已有有效分段，只补缺失段")
    hg.add_argument("--fit-duration", dest="fit", action="store_true", help="拼接前把每段裁到 plan 的目标秒数（精确总时长）")
    hg.set_defaults(func=cmd_h3gen)

    al = sub.add_parser("all", help="全链路：H3 分段生成拼接 → 配音字幕BGM 成片")
    al.add_argument("--plan", required=True)
    al.add_argument("--dry-run", action="store_true", help="只打印预估，不提交、不出片")
    al.add_argument("--yes", action="store_true", help="确认付费并执行")
    al.add_argument("--only", default=None, help="只生成这些段（逗号分隔），用于单段重跑")
    al.add_argument("--skip-existing", action="store_true", help="跳过已有有效分段，只补缺失段")
    al.add_argument("--fit-duration", dest="fit", action="store_true", help="拼接前把每段裁到 plan 的目标秒数")
    al.add_argument("--tries", type=int, default=DEFAULT_TRIES)
    al.add_argument("--reuse-parts", action="store_true")
    al.set_defaults(func=cmd_all)

    a = ap.parse_args()
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
