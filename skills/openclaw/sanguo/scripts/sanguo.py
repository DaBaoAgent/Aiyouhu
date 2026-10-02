#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sanguo — 三国 IP 软广短视频工具（音色参考配音 / 对口型 / 字幕+BGM 后期）。

项目根运行。**中文参数一律经本脚本（UTF-8 源码）调用下游**，避免 PowerShell 命令行
把中文 argv 传成乱码（UTF-8 字节被按 GBK 解码）。

    python skills/openclaw/sanguo/scripts/sanguo.py list
    python skills/openclaw/sanguo/scripts/sanguo.py tts --voice 诸葛亮-老年 --text 口播.txt \
        -o outputs/<topic>/assets/口播_诸葛亮.mp3
    python skills/openclaw/sanguo/scripts/sanguo.py lipsync \
        --image outputs/<topic>/assets/角色图.png --audio outputs/<topic>/assets/口播_诸葛亮.mp3 \
        -d 15 -o outputs/<topic>/assets/clip_lipsync.mp4
    # 字幕（sanguo 统一样式）+ 可选烧录
    python skills/openclaw/sanguo/scripts/sanguo.py ass \
        --spec outputs/<topic>/字幕.json --burn outputs/<topic>/assets/clip_lipsync.mp4 \
        -o outputs/<topic>/成片_15秒.mp4
    # 字幕 + BGM 一步到位
    python skills/openclaw/sanguo/scripts/sanguo.py post \
        --video outputs/<topic>/assets/clip_lipsync.mp4 --spec outputs/<topic>/字幕.json \
        --bgm 诸葛亮BGM -o outputs/<topic>/成片_15秒.mp4

依赖：autodl-h3-video/scripts/h3_video.py（H3 付费）、asr.py、subtitle_ops.py、video_ops.py。
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

H3 = "skills/openclaw/autodl-h3-video/scripts/h3_video.py"
ASR = "skills/shared/scripts/asr.py"
SUB = "skills/shared/scripts/subtitle_ops.py"
VOPS = "skills/shared/scripts/video_ops.py"

# ── sanguo 统一字幕样式 ─────────────────────────────────────────────
# koubo 字体/字号 + 位置下移到画面下三分之一 + 去标点 + 入场上弹/持续轻跳 + 重点词黄字。
SUB_FONT = "Microsoft YaHei"       # 与 koubo 一致
HL_YELLOW = "&H0000FFFF&"          # ASS BGR 黄（取自 clipify opus 样式的同一色值）
WHITE = "&H00FFFFFF&"
PUNCT = set("，。、！？；：、“”‘’（）《》〈〉【】…—～·,.!?;:\"'()[]{}<>!")

ASS_HEAD = """[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,{font},{size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,{ml},{mr},{mv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

# 角色库：参考图（人物参考图/三国2010/）｜音色（三国音色/）｜BGM（三国音色/三国BGM/）
CHARACTERS: dict[str, dict] = {
    "诸葛亮-老年": {
        "ref": "000-E 诸葛亮·老年｜52岁·五丈原（全身·含轮椅）.png",
        "ref_half": "000-F 诸葛亮·老年｜52岁·五丈原（半身·纯人物）.png",
        "voice": "诸葛亮-老年.mp3", "bgm": ["诸葛亮BGM.mp3", "卧龙吟.mp3"]},
    "诸葛亮-垂暮": {
        "ref": "000-F 诸葛亮·老年｜52岁·五丈原（半身·纯人物）.png",
        "voice": "诸葛亮-垂暮.mp3", "bgm": ["丞相保重.mp3", "卧龙吟.mp3"]},
    "诸葛亮-青年": {
        "ref": "000-A 诸葛亮·青年｜27岁·三顾出山（全身·含轮椅）.png",
        "ref_half": "000-B 诸葛亮·青年｜27岁·三顾出山（半身·纯人物）.png",
        "voice": "诸葛亮-年轻.mp3", "bgm": ["卧龙吟.mp3"]},
    "刘备": {"ref": "001 刘备｜主公（2010版·于和伟）.png", "voice": "刘备.mp3", "bgm": ["卧龙吟.mp3"]},
    "曹操": {"ref": "024 曹操｜魏王（2010版·陈建斌）.png", "voice": "曹操.mp3", "bgm": ["丞相保重.mp3"]},
    "司马懿": {"ref": "025 司马懿｜大都督（2010版·倪大红）.png", "voice": "司马懿.mp3", "bgm": ["丞相保重.mp3"]},
}


def find_root() -> Path:
    here = Path(__file__).resolve()
    for p in [here, *here.parents]:
        if (p / "skills" / "shared" / "scripts" / "voice_clone.py").is_file():
            return p
    sys.exit("找不到项目根（未定位到 skills/shared/scripts/voice_clone.py）")


def run(root: Path, args: list) -> None:
    print("»", " ".join(str(a) for a in args), flush=True)
    r = subprocess.run([str(a) for a in args], cwd=str(root))
    if r.returncode != 0:
        name = Path(str(args[1])).name if len(args) > 1 else str(args[0])
        sys.exit(f"命令失败（exit {r.returncode}）：{name}")


def _abspath(root: Path, p: str) -> Path:
    q = Path(p)
    return q if q.is_absolute() else root / q


def _out(root: Path, p: str) -> Path:
    out = _abspath(root, p)
    out.parent.mkdir(parents=True, exist_ok=True)
    return out


def _resolve(root: Path, name: str, subdir: Path, exts=(".mp3",)) -> Path:
    p = Path(name)
    if p.is_absolute() and p.is_file():
        return p
    for cand in [subdir / name, *[subdir / (name + e) for e in exts], root / name]:
        if cand.is_file():
            return cand
    sys.exit(f"找不到素材：{name}")


def resolve_voice(root: Path, name: str) -> Path:
    return _resolve(root, name, root / "三国音色")


def resolve_bgm(root: Path, name: str) -> Path:
    return _resolve(root, name, root / "三国音色" / "三国BGM")


# ── 字幕：sanguo 统一样式 ───────────────────────────────────────────
def strip_punct(s: str) -> str:
    return "".join(ch for ch in s if ch not in PUNCT)


def _anim(dur_s: float) -> str:
    """入场上弹（70%→112%→100%）+ 显示期间每 0.6s 轻跳（100%↔103%），等比不变形。"""
    parts = [r"\fscx70\fscy70", r"\t(0,120,\fscx112\fscy112)", r"\t(120,240,\fscx100\fscy100)"]
    start, total = 240, int(round(dur_s * 1000))
    while start + 600 <= total:
        parts += [rf"\t({start},{start + 300},\fscx103\fscy103)",
                  rf"\t({start + 300},{start + 600},\fscx100\fscy100)"]
        start += 600
    return "{" + "".join(parts) + "}"


def _highlighted(text: str, hls: list) -> str:
    text = strip_punct(text)
    spans = sorted((text.find(h), text.find(h) + len(h)) for h in hls if text.find(h) >= 0)
    out, cur = [], 0
    for a, b in spans:
        if a < cur:
            continue
        out += [text[cur:a], f"{{\\c{HL_YELLOW}}}{text[a:b]}{{\\c{WHITE}}}"]
        cur = b
    out.append(text[cur:])
    return "".join(out)


def _fmt_t(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec - h * 3600 - m * 60
    return f"{h}:{m:02d}:{s:05.2f}"


def write_ass(spec: dict, out: Path, font_size: int = 0, margin_v: float = 0.26) -> Path:
    """spec = {width,height,lines:[{start,end,text,hl:[...]}, ...]} -> sanguo 样式 ASS。"""
    w = int(spec.get("width", 768))
    h = int(spec.get("height", 1344))
    size = font_size or max(34, int(min(w, h) * 0.0625))
    ml = mr = int(w * 0.06)
    mv = int(h * margin_v)
    head = ASS_HEAD.format(w=w, h=h, font=SUB_FONT, size=size, ml=ml, mr=mr, mv=mv)
    ev = []
    for ln in spec["lines"]:
        a, b = float(ln["start"]), float(ln["end"])
        ev.append("Dialogue: 0,{},{},Sub,,0,0,0,,{}{}".format(
            _fmt_t(a), _fmt_t(b), _anim(b - a), _highlighted(ln["text"], ln.get("hl", []))))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(head + "\n".join(ev) + "\n", encoding="utf-8-sig")
    return out


def _load_spec(p: str) -> dict:
    path = Path(p)
    if not path.is_file():
        sys.exit(f"字幕 spec 不存在：{p}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def find_ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    for cand in [Path.home() / "bin" / "ffmpeg.exe", Path("C:/ffmpeg/bin/ffmpeg.exe")]:
        if cand.is_file():
            return str(cand)
    sys.exit("找不到 ffmpeg（请加入 PATH，或放到 ~/bin/ffmpeg.exe）")


def _burn_ass(root: Path, src: Path, ass: Path, out: Path) -> Path:
    """以 ass 滤镜把字幕烧进视频（cwd=ass 目录，避免中文路径转义）。"""
    mp4 = out if out.suffix.lower() == ".mp4" else out.with_suffix(".mp4")
    r = subprocess.run([find_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
                        "-i", str(src), "-filter_complex", f"[0:v]ass={ass.name}[v]",
                        "-map", "[v]", "-map", "0:a", "-c:v", "libx264", "-crf", "20",
                        "-preset", "medium", "-c:a", "copy", str(mp4)], cwd=str(ass.parent))
    if r.returncode != 0:
        sys.exit(f"字幕烧录失败（exit {r.returncode}）")
    return mp4


def cmd_list(a) -> int:
    root = find_root()
    print("角色库：")
    for k, v in CHARACTERS.items():
        print(f"  {k}")
        print(f"    参考图：{v.get('ref')}" + (f" ｜ 半身：{v['ref_half']}" if v.get("ref_half") else ""))
        print(f"    音色：{v.get('voice')} ｜ BGM：{', '.join(v.get('bgm', []))}")
    print("\n音色文件（三国音色/）：", ", ".join(f.name for f in sorted((root / "三国音色").glob("*.mp3"))))
    print("BGM（三国音色/三国BGM/）：", ", ".join(f.name for f in sorted((root / "三国音色" / "三国BGM").glob("*.mp3"))))
    return 0


def cmd_tts(a) -> int:
    root = find_root()
    voice = resolve_voice(root, a.voice)
    text = "".join(Path(a.text).read_text(encoding="utf-8-sig").split())
    if not text:
        sys.exit("文案为空")
    out = _out(root, a.out)
    st = Path(str(out) + ".state.json")
    if st.exists() and a.fresh:
        st.unlink()
    run(root, [sys.executable, root / H3, "-w", "tts", "-a", str(voice),
               "--prompt", text, "--no-verify", "-o", str(out)])
    return 0


def cmd_lipsync(a) -> int:
    root = find_root()
    img = _abspath(root, a.image)
    aud = _abspath(root, a.audio)
    if not img.is_file():
        sys.exit(f"参考图不存在：{img}")
    if not aud.is_file():
        sys.exit(f"音频不存在：{aud}")
    out = _out(root, a.out)
    st = Path(str(out) + ".state.json")
    if st.exists() and a.fresh:
        st.unlink()
    run(root, [sys.executable, root / H3, "-w", "image_audio", "-i", str(img), "-a", str(aud),
               "-r", a.res, "-d", str(a.duration), "-o", str(out)])
    return 0


def cmd_ass(a) -> int:
    root = find_root()
    spec = _load_spec(a.spec)
    out = _out(root, a.out)
    ass = out if out.suffix.lower() == ".ass" else out.with_suffix(".ass")
    write_ass(spec, ass, font_size=a.font_size, margin_v=a.margin_v)
    print("字幕：", ass)
    if a.burn:
        src = _abspath(root, a.burn)
        if not src.is_file():
            sys.exit(f"视频不存在：{src}")
        print("✅ 成片：", _burn_ass(root, src, ass, out))
    return 0


def cmd_post(a) -> int:
    root = find_root()
    video = _abspath(root, a.video)
    if not video.is_file():
        sys.exit(f"视频不存在：{video}")
    out = _out(root, a.out)
    scratch = root / "outputs" / "_scratch" / f"sanguo_{out.stem}"
    scratch.mkdir(parents=True, exist_ok=True)
    cur = video
    if a.spec:
        ass = scratch / "字幕.ass"
        write_ass(_load_spec(a.spec), ass, font_size=a.font_size, margin_v=a.margin_v)
        cur = _burn_ass(root, cur, ass, scratch / "subbed.mp4")
        print("字幕（sanguo 样式）：", ass)
    elif not a.no_subtitle:
        srt = Path(a.srt) if a.srt else scratch / "字幕.srt"
        if not (a.srt and srt.is_file()):
            run(root, [sys.executable, root / ASR, "transcribe", "-i", str(video), "-o", str(srt),
                       "--format", "srt", "--language", "zh", "--model", a.asr_model,
                       "--device", "cpu", "--compute-type", "int8"])
        subbed = scratch / "subbed.mp4"
        run(root, [sys.executable, root / SUB, "burn", "-i", str(cur), "--sub", str(srt), "-o", str(subbed)])
        cur = subbed
    if a.bgm:
        bgm = resolve_bgm(root, a.bgm)
        run(root, [sys.executable, root / VOPS, "bgm", "-i", str(cur), "-o", str(out),
                   "--music", str(bgm), "--voice-volume", "1.0", "--music-volume", str(a.bgm_volume)])
    else:
        shutil.copyfile(cur, out)
    print("✅ 成片：", out)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="三国 IP 软广短视频工具")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list", help="列出角色 / 音色 / BGM")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("tts", help="H3 indextts2 音色参考配音")
    p.add_argument("--voice", required=True, help="角色音色名（如 诸葛亮-老年）或路径")
    p.add_argument("--text", required=True, help="口播文案 txt（UTF-8，一行或整段）")
    p.add_argument("-o", "--out", required=True)
    p.add_argument("--fresh", action="store_true", help="清除旧断点重跑")
    p.set_defaults(func=cmd_tts)

    p = sub.add_parser("lipsync", help="H3 image_audio 图+音频对口型")
    p.add_argument("--image", required=True)
    p.add_argument("--audio", required=True)
    p.add_argument("-r", "--res", default="768p竖")
    p.add_argument("-d", "--duration", type=int, default=15, help="秒数 1-15")
    p.add_argument("-o", "--out", required=True)
    p.add_argument("--fresh", action="store_true")
    p.set_defaults(func=cmd_lipsync)

    p = sub.add_parser("ass", help="由 JSON 时间轴生成 sanguo 样式字幕（可选烧录）")
    p.add_argument("--spec", required=True, help="字幕 JSON：{width,height,lines:[{start,end,text,hl}]}")
    p.add_argument("--burn", default="", help="可选：要烧录的输入视频")
    p.add_argument("-o", "--out", required=True, help="输出 .ass；给 --burn 时输出 .mp4")
    p.add_argument("--font-size", type=int, default=0, help="覆盖字号（默认 min(W,H)*0.0625）")
    p.add_argument("--margin-v", type=float, default=0.26, help="下边距=H*该比例（0.26≈画面下三分之一）")
    p.set_defaults(func=cmd_ass)

    p = sub.add_parser("post", help="字幕（sanguo 样式 / ASR）+ BGM 后期")
    p.add_argument("--video", required=True)
    p.add_argument("--spec", default="", help="字幕 JSON（sanguo 样式；优先于 ASR）")
    p.add_argument("--bgm", default="", help="BGM 名（三国音色/三国BGM/）或路径；空=不加")
    p.add_argument("--bgm-volume", type=float, default=0.16)
    p.add_argument("--srt", default="", help="已有字幕文件（跳过 ASR）")
    p.add_argument("--no-subtitle", action="store_true")
    p.add_argument("--asr-model", default="base")
    p.add_argument("--font-size", type=int, default=0)
    p.add_argument("--margin-v", type=float, default=0.26)
    p.add_argument("-o", "--out", required=True)
    p.set_defaults(func=cmd_post)

    a = ap.parse_args()
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
