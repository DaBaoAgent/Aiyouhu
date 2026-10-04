#!/usr/bin/env python3
"""fuke · 爆款视频复刻（hypit 引擎）· Easel 侧封装。

把 Easel 的产物规范（outputs/<主题>/、成品放根、媒体直链）落到 hypit 复刻流程上。
设计上只做**机械动作**，创作判断交给读 hypit 技能页的 Agent：

  check      环境自检（项目根 / hypit 入口 / node / ffmpeg / 媒体直链基址）
  workspace  创建并返回 hypit 工作区（outputs/<topic>/assets/hypit）
  fetch      下载参考视频链接到工作区 references/<name>/source.mp4
  export     把某次 Build 的 Output 导出到 outputs/<topic>/（成品放项目根）
  verify     成片自检（非空 / 时长 / 画幅 / 视频流）
  link       生成 Easel Web 媒体直链

路径铁律：先 cd 到项目根（含 .env 与 skills/shared/scripts/）。不得在 workspace 跑。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.parse
from pathlib import Path


def find_root() -> Path:
    here = Path(__file__).resolve()
    for p in (here, *here.parents):
        if (p / "skills" / "shared" / "scripts" / "output_paths.py").is_file():
            return p
    print("错误：找不到项目根（未定位到 skills/shared/scripts/output_paths.py）", file=sys.stderr)
    raise SystemExit(1)


ROOT = find_root()
HYPIT_DIR = Path(os.environ.get("HYPIT_DIR") or (ROOT / "hypit")).resolve()
ENTRY = HYPIT_DIR / "bin" / "hypit.mjs"
MEDIA_BASE = os.environ.get("EASEL_MEDIA_BASE", "http://localhost:7860/api/media").rstrip("/")

sys.path.insert(0, str(ROOT / "skills" / "shared" / "scripts"))
try:  # 共享产物路径门禁（缺失时退化为本地拼接，宁可缺门禁也不误报缺配置）
    from output_paths import OutputPathError, validate_output_path  # type: ignore
except Exception:  # pragma: no cover
    OutputPathError = ValueError  # type: ignore

    def validate_output_path(value, *, allow_system=False, create_parent=False):  # type: ignore
        p = Path(value)
        p = p if p.is_absolute() else (ROOT / p)
        if create_parent:
            p.parent.mkdir(parents=True, exist_ok=True)
        return p


def fail(msg: str, code: int = 1):
    print(f"错误：{msg}", file=sys.stderr)
    raise SystemExit(code)


def safe_output(rel: str, *, create_parent: bool = False) -> Path:
    try:
        return validate_output_path(rel, create_parent=create_parent)
    except OutputPathError as exc:  # type: ignore[misc]
        fail(str(exc))


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=str(cwd) if cwd else None,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def hypit(args: list[str], cwd: Path | None = None, quiet: bool = False) -> subprocess.CompletedProcess:
    if not ENTRY.is_file():
        fail(f"找不到 hypit 入口：{ENTRY}（可用 HYPIT_DIR 覆盖；先确认 hypit/ 已复制到项目根）")
    r = run(["node", str(ENTRY), *args], cwd=cwd)
    if r.returncode != 0:
        fail(f"hypit 命令失败：{' '.join(args[:3])}…\n{(r.stderr or r.stdout)[-1200:]}")
    if not quiet and r.stdout.strip():
        print(r.stdout.rstrip())
    return r


def hyper_workspace(topic: str) -> Path:
    """创建/返回 hypit 工作区：outputs/<topic>/assets/hypit（含 package.json）。"""
    ws = safe_output(f"outputs/{topic}/assets/hypit", create_parent=True)
    ws.mkdir(parents=True, exist_ok=True)
    pkg = ws / "package.json"
    if not pkg.is_file():
        pkg.write_text(
            json.dumps({"name": "easel-fuke", "version": "0.0.0", "private": True, "type": "module"},
                       ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return ws


# ── 子命令 ──────────────────────────────────────────────────────────────
def cmd_check(a) -> int:
    print(f"项目根     ：{ROOT}")
    print(f"hypit 目录 ：{HYPIT_DIR}")
    ok = True
    if ENTRY.is_file():
        r = run(["node", str(ENTRY), "version"])
        lines = [l for l in (r.stdout or "").splitlines() if l.strip()]
        ver = next((l for l in lines if l.strip().startswith("@hypit/")), "(无版本输出)")
        print(f"hypit      ：{ver.strip()}")
        ok = ok and r.returncode == 0
    else:
        print("hypit      ：✗ 未找到入口（确认 hypit/ 已在项目根）")
        ok = False
    for exe in ("node", "ffmpeg", "ffprobe"):
        mark = "✓" if shutil.which(exe) else "✗ 未找到"
        print(f"{exe:<10} ：{mark}")
        if exe == "node" and not shutil.which(exe):
            ok = False
    print(f"媒体直链   ：{MEDIA_BASE}")
    print("结论       ：" + ("OK" if ok else "需修复"))
    return 0 if ok else 1


def cmd_workspace(a) -> int:
    ws = hyper_workspace(a.topic)
    print(f"hypit 工作区 → {ws}")
    print("下一步：fetch 收参考视频，然后在工作区跑 runtime init / transcribe / build。")
    return 0


def cmd_fetch(a) -> int:
    ws = hyper_workspace(a.topic)
    name = a.name or "ref"
    dest_rel = f"references/{name}/source.mp4"
    dest = ws / "references" / name / "source.mp4"
    if dest.exists():
        fail(f"参考视频已存在：{dest}（换 --name 或先删除）")
    prep = run(["node", str(ENTRY), "media", "prepare-fetch"], cwd=ws)
    if prep.returncode != 0:
        print("提示：media prepare-fetch 未成功，仍尝试 fetch（可能需要 uv / 网络）。", file=sys.stderr)
    hypit(["media", "fetch", a.url, "--to", dest_rel], cwd=ws)
    if not dest.is_file():
        fail(f"fetch 结束但未见文件：{dest}")
    print(f"✅ 参考视频 → {dest}")
    return 0


def cmd_export(a) -> int:
    ws = hyper_workspace(a.topic)
    fname = a.filename or (a.output if a.output.lower().endswith(
        (".mp4", ".mov", ".webm", ".mkv", ".png", ".jpg", ".jpeg", ".wav", ".mp3")) else a.output + ".mp4")
    dest = safe_output(f"outputs/{a.topic}/{fname}", create_parent=True)
    hypit(["get", a.build, "--output", a.output, "--to", str(dest)], cwd=ws)
    if not dest.is_file():
        fail(f"导出结束但未见文件：{dest}")
    print(f"✅ 成片 → {dest}")
    return 0


def cmd_verify(a) -> int:
    path = safe_output(f"outputs/{a.topic}/{a.file}")
    if not path.is_file():
        fail(f"找不到成片：{path}")
    size = path.stat().st_size
    info: dict = {}
    try:
        r = run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(path)])
        info = json.loads(r.stdout or "{}")
    except Exception:
        info = {}
    dur = float((info.get("format") or {}).get("duration") or 0)
    vid = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
    print(f"文件 ：{path}")
    print(f"大小 ：{size / 1e6:.2f} MB")
    print(f"时长 ：{dur:.2f} s")
    print(f"画幅 ：{vid.get('width', '?')}x{vid.get('height', '?')}")
    ok = size > 100_000 and dur > 0 and bool(vid)
    print("结论 ：" + ("OK" if ok else "不合格（空 / 无视频流 / 过短）"))
    return 0 if ok else 1


def cmd_link(a) -> int:
    quoted = "/".join(urllib.parse.quote(seg) for seg in (a.topic, a.file) if seg)
    print(f"{MEDIA_BASE}/{quoted}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="fuke · 爆款视频复刻（hypit 引擎）· Easel 侧封装")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check", help="环境自检（只读）")

    w = sub.add_parser("workspace", help="创建/返回 hypit 工作区")
    w.add_argument("--topic", required=True)

    f = sub.add_parser("fetch", help="下载参考视频链接")
    f.add_argument("--topic", required=True)
    f.add_argument("--url", required=True)
    f.add_argument("--name", default="ref")

    e = sub.add_parser("export", help="导出 Build Output 到 outputs/<topic>/")
    e.add_argument("--topic", required=True)
    e.add_argument("--build", required=True)
    e.add_argument("--output", required=True)
    e.add_argument("--filename")

    v = sub.add_parser("verify", help="成片自检")
    v.add_argument("--topic", required=True)
    v.add_argument("--file", required=True)

    l = sub.add_parser("link", help="生成媒体直链")
    l.add_argument("--topic", required=True)
    l.add_argument("--file", required=True)
    return p


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    return {
        "check": cmd_check,
        "workspace": cmd_workspace,
        "fetch": cmd_fetch,
        "export": cmd_export,
        "verify": cmd_verify,
        "link": cmd_link,
    }[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
