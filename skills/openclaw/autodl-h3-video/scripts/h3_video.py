#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AutoDL.Art MiniMax H3 视频生成通用客户端（autodl 伞形技能）
================================================================
支持全部 H3 ComfyUI 工作流：
  multi_image  多图参考生成视频 (minimax_h3_lightx2v_v5)  duration 1-10s
  image_audio  图+音频对口型   (minimax_h3_image_audio_to_video)  audio_duration 1-15s
  text2video   文生视频        (minimax_h3_lightx2v_no_pic)      duration 1-10s
  first_last   首尾帧生成      (minimax_h3_lightx2v)             duration 1-10s
  tts          indextts2 TTS   (indextts2-v1)

用法：
  单条: python h3_gen.py -w multi_image --prompt "提示词" -i 图1.jpg -i 图2.jpg -r 1080p竖 -d 10 -o out.mp4
        python h3_gen.py -w image_audio -i 图.jpg -a 音.mp3 -r 768p竖 -d 5 -o out.mp4
  批量: python h3_gen.py -w multi_image --ideas 选题.txt -i 图1.jpg -i 图2.jpg -r 1080p竖 -d 10 --out-prefix video --concurrency 10
  续传: 同上命令加 --resume（中断后重跑：已完成跳过、未完成续查、失败重提）
  关闭预处理/验收: --no-resize --no-verify

选题文件格式（batch_h3_v3 兼容）:
  1. 标题
  提示词正文
  2. 标题
  提示词正文

配置：环境变量或同目录 .env 文件 AUTODL_API_KEY
价格：480p ¥0.04/秒  768p ¥0.06/秒  1080p ¥0.10/秒
日志：每条生成自动追加 JSONL 到输出目录 h3_gen_log.jsonl（含成本/耗时/验收结果）
"""
import argparse
import base64
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache

import requests

BASE_URL = "https://autodl.art"
WORKFLOWS = {
    "multi_image": "minimax_h3_lightx2v_v5",
    "image_audio": "minimax_h3_image_audio_to_video",
    "text2video": "minimax_h3_lightx2v_no_pic",
    "first_last": "minimax_h3_lightx2v",
    "tts": "indextts2-v1",
}
RESOLUTIONS = ["480p竖", "768p竖", "1080p竖", "480p横", "768p横", "1080p横"]
PRICE_PER_SEC = {"480p": 0.04, "768p": 0.06, "1080p": 0.10}  # ¥/秒
POLL_INTERVAL = 20
MAX_WAIT = 25 * 60
QUERY_RETRIES = 5
DOWNLOAD_RETRIES = 4
RETRY_DELAY = 10
RESIZE_MAX_SIDE = 1280               # 参考图最长边上限 px
RESIZE_MAX_BYTES = 1.5 * 1024 * 1024  # 参考图 base64 前字节上限
FFPROBE_CANDIDATES = [
    os.environ.get("FFPROBE", ""),
    shutil.which("ffprobe") or "",
    "C:/Users/xxx13/ffmpeg/ffmpeg-8.1.1-essentials_build/bin/ffprobe.exe",
]
EXPECTED_SIZE = {  # 验收用期望宽高（宽x高），按宽高比宽松匹配
    "480p竖": (480, 854), "768p竖": (768, 1344), "1080p竖": (1080, 1920),
    "480p横": (854, 480), "768p横": (1344, 768), "1080p横": (1920, 1080),
}

_state_lock = threading.Lock()
_log_lock = threading.Lock()


def res_key(resolution: str) -> str:
    """'1080p竖' → '1080p'（成本查表键；[:4] 会取成 '1080' 导致成本恒 0）"""
    return resolution[:resolution.index("p") + 1] if "p" in resolution else resolution


def load_env_file(path=".env"):
    here = os.path.dirname(os.path.abspath(__file__))
    # Easel 项目根 .env（scripts/<skill> → openclaw → skills → 项目根）
    root_env = os.path.normpath(os.path.join(here, "..", "..", "..", "..", ".env"))
    candidates = [path, os.path.join(here, ".env"), root_env]
    for p in candidates:
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    if k.strip() == "AUTODL_API_KEY":
                        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def headers():
    key = os.environ.get("AUTODL_API_KEY", "")
    if not key:
        sys.exit("错误: 未设置 AUTODL_API_KEY（https://autodl.art/large-model/tokens 创建，分组选 ComfyUI）")
    return {"Authorization": key, "Content-Type": "application/json"}


# ---------- 图片预处理（P1-6）----------

@lru_cache(maxsize=64)
def to_data_url(path_or_url: str, resize: bool = True) -> str:
    """本地文件 → data URL；URL 原样返回。resize=True 时用 Pillow 缩到 ≤1280px/≤1.5MB。"""
    if path_or_url.startswith(("http://", "https://", "data:")):
        return path_or_url
    if not os.path.exists(path_or_url):
        sys.exit(f"错误: 文件不存在: {path_or_url}（可传公网URL，本地文件自动转base64）")

    def raw_b64():
        mime, _ = mimetypes.guess_type(path_or_url)
        mime = mime or "application/octet-stream"
        with open(path_or_url, "rb") as f:
            return f"data:{mime};base64,{base64.b64encode(f.read()).decode()}"

    # 音频等非图片素材：直接 base64，不做 PIL 缩放（tts / image_audio 的 ref_audio）
    _ext = os.path.splitext(path_or_url)[1].lower()
    if _ext in (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma"):
        return raw_b64()
    if not resize:
        return raw_b64()
    try:
        from PIL import Image
        import io
        img = Image.open(path_or_url)
        w, h = img.size
        if max(w, h) > RESIZE_MAX_SIDE:
            ratio = RESIZE_MAX_SIDE / max(w, h)
            img = img.resize((max(1, int(w * ratio)), max(1, int(h * ratio))), Image.LANCZOS)
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            bg = Image.new("RGB", img.size, (255, 255, 255))  # 透明→白底，产品图不黑底
            bg.paste(img, mask=img.split()[-1])
            img = bg
        else:
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85)
        data = buf.getvalue()
        if len(data) > RESIZE_MAX_BYTES:  # 仍超限则降质重压
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=65)
            data = buf.getvalue()
        print(f"     参考图预处理: {os.path.basename(path_or_url)} {w}x{h} -> {img.size[0]}x{img.size[1]} {len(data)/1024:.0f}KB")
        return f"data:image/jpeg;base64,{base64.b64encode(data).decode()}"
    except ImportError:
        return raw_b64()


# ---------- API 调用（P0-1/P0-2 重试）----------

def http_request(method, url, retries, **kwargs):
    """带重试的 GET（SSLError/ConnectionError/Timeout/5xx 均重试）。POST 不重试（防重复扣费）。"""
    for attempt in range(retries):
        try:
            resp = requests.request(method, url, **kwargs)
            if resp.status_code >= 500 and method.upper() == "GET":
                raise requests.exceptions.ConnectionError(f"HTTP {resp.status_code}")
            return resp
        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError,
                requests.exceptions.Timeout) as e:
            if attempt == retries - 1:
                raise
            print(f"    网络抖动(第{attempt+1}/{retries}次重试): {e}", flush=True)
            time.sleep(RETRY_DELAY)


def create_task(workflow_id: str, payload: dict) -> str:
    url = f"{BASE_URL}/api/v1/comfyui/comfyui_workflow/{workflow_id}"
    print(f"[1/4] 提交任务 -> {url}")
    resp = requests.post(url, headers=headers(), json=payload, timeout=180)
    try:
        body = resp.json()
    except ValueError:
        raise RuntimeError(f"提交失败 HTTP {resp.status_code}，非 JSON: {resp.text[:300]}")
    if body.get("code") != "Success":
        raise RuntimeError(f"提交失败: {body.get('msg') or body}")
    task_id = body["data"]["task_id"]
    print(f"     task_id={task_id}  status={body['data'].get('status')}")
    return task_id


def query_task(task_id: str) -> dict:
    url = f"{BASE_URL}/api/v1/comfyui/comfyui_workflow/result/{task_id}"
    resp = http_request("GET", url, QUERY_RETRIES, headers=headers(), timeout=30)
    try:
        body = resp.json()
    except ValueError:
        raise RuntimeError(f"查询失败 HTTP {resp.status_code}: {resp.text[:300]}")
    if body.get("code") != "Success":
        raise RuntimeError(f"查询失败: {body.get('msg') or body}")
    return body.get("data", {})


def poll_task(task_id: str, label: str = "") -> str:
    deadline = time.time() + MAX_WAIT
    while time.time() < deadline:
        data = query_task(task_id)
        status = data.get("status", "")
        print(f"     {label}status={status}  耗时={data.get('duration')}s", flush=True)
        if status == "SUCCESS":
            results = data.get("results") or []
            for prefer in ("video", "audio"):
                for r in results:
                    if r.get("type") == prefer and r.get("url"):
                        return r["url"]
            for r in results:
                if r.get("url"):
                    return r["url"]
            raise RuntimeError(f"任务完成但无结果 URL: {data}")
        if status in ("FAILED", "ERROR", "CANCELLED"):
            raise RuntimeError(f"任务失败: {data}")
        time.sleep(POLL_INTERVAL)
    raise RuntimeError(f"等待超时（{MAX_WAIT//60} 分钟）: {task_id}")


def download(url: str, out_path: str):
    print(f"[3/4] 下载成片 -> {out_path}")
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    tmp = out_path + ".part"
    for attempt in range(DOWNLOAD_RETRIES):
        try:
            with requests.get(url, timeout=300, stream=True) as resp:
                resp.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=1 << 16):
                        f.write(chunk)
            os.replace(tmp, out_path)
            print(f"     完成: {out_path} ({os.path.getsize(out_path)/1024/1024:.1f} MB)")
            return
        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError,
                requests.exceptions.Timeout, requests.exceptions.HTTPError) as e:
            if attempt == DOWNLOAD_RETRIES - 1:
                raise
            print(f"    下载抖动(第{attempt+1}/{DOWNLOAD_RETRIES}次重试): {e}", flush=True)
            time.sleep(RETRY_DELAY)


# ---------- 自动验收（P1-7）----------

def find_ffprobe():
    for c in FFPROBE_CANDIDATES:
        if c and os.path.exists(c):
            return c
    return shutil.which("ffprobe") or None


def verify_video(path: str, expect_duration: float, resolution: str) -> dict:
    """ffprobe 校验：可解码/时长±1s/宽高比匹配/大小>1MB。返回结果 dict，不抛异常。"""
    result = {"ok": False, "checks": {}}
    if not os.path.exists(path):
        result["checks"]["size"] = "FAIL 文件不存在"
        return result
    size = os.path.getsize(path)
    if size < 1024 * 1024:
        result["checks"]["size"] = f"FAIL <1MB ({size} bytes)"
        return result
    result["checks"]["size"] = "OK"
    ffp = find_ffprobe()
    if not ffp:
        result["checks"]["ffprobe"] = "SKIP 未找到 ffprobe"
        result["ok"] = True
        return result
    try:
        out = subprocess.run(
            [ffp, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,duration", "-of", "json", path],
            capture_output=True, text=True, timeout=60)
        info = json.loads(out.stdout or "{}")
        st = (info.get("streams") or [{}])[0]
        w, h = int(st.get("width", 0)), int(st.get("height", 0))
        dur = float(st.get("duration", 0))
        exp_w, exp_h = EXPECTED_SIZE.get(resolution, (0, 0))
        checks = result["checks"]
        dur_ok = abs(dur - expect_duration) <= 1.0
        checks["duration"] = f"{dur:.1f}s vs 期望{expect_duration}s" + (" OK" if dur_ok else " ⚠️偏差")
        if exp_w and w and h:
            ratio = w / h
            exp_ratio = exp_w / exp_h
            ratio_ok = abs(ratio - exp_ratio) / exp_ratio < 0.15
            checks["resolution"] = f"{w}x{h}" + (" OK" if ratio_ok else f" ⚠️宽高比不符(期望{resolution})")
        else:
            checks["resolution"] = f"{w}x{h} 无法校验"
        bad = [v for k, v in checks.items() if "SKIP" not in v and any(x in v for x in ("FAIL", "⚠️", "ERROR"))]
        result["ok"] = not bad
        if bad:
            checks["warn"] = "有参数偏差，需人工复核"
        return result
    except Exception as e:
        result["checks"]["ffprobe"] = f"ERROR {e}"
        return result


# ---------- 日志（P1-7）----------

def log_record(rec: dict, log_path: str):
    if not log_path:
        return
    with _log_lock:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ---------- 状态管理（P0-3 断点续传）----------

def load_state(state_file: str) -> dict:
    if state_file and os.path.exists(state_file):
        with open(state_file, encoding="utf-8") as f:
            return json.load(f)
    return {"version": 1, "tasks": {}}


def save_state(state_file: str, state: dict):
    with _state_lock:
        tmp = state_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, state_file)


# ---------- 任务执行 ----------

def build_payload(workflow, prompt, images, audio, resolution, duration, resize) -> dict:
    if workflow == "image_audio":
        return {"audio_duration": duration, "ref_audio_0": to_data_url(audio, resize),
                "ref_image_0": to_data_url(images[0], resize), "resolution": resolution}
    if workflow == "multi_image":
        payload = {"duration": duration, "prompt": prompt, "resolution": resolution}
        for i in range(len(images)):
            payload[f"ref_image_{i}"] = to_data_url(images[i], resize)
        return payload
    if workflow == "first_last":
        # schema: required first_frame / last_frame（不是 ref_image_N）
        return {"duration": duration, "prompt": prompt, "resolution": resolution,
                "first_frame": to_data_url(images[0], resize),
                "last_frame": to_data_url(images[1], resize)}
    if workflow == "text2video":
        return {"duration": duration, "prompt": prompt, "resolution": resolution}
    if workflow == "tts":
        # indextts2-v1 schema：prompt_simple=音色参考音频(audio)，prompt_text=待合成文本(string)，
        # emo_control_method 必填(enum)；默认「与音色参考音频相同」以复刻参考音色。
        return {"prompt_text": prompt, "prompt_simple": to_data_url(audio, resize),
                "emo_control_method": "与音色参考音频相同"}
    sys.exit(f"未知工作流: {workflow}")


def run_one(key, task, args, log_path, state, state_file):
    """单任务：提交/续传 → 轮询 → 下载 → 验收 → 日志。失败标记 failed 并落盘，不中断批量。"""
    workflow_id = WORKFLOWS[args.workflow]
    tid = task.get("task_id")
    if not tid:
        payload = build_payload(args.workflow, task["prompt"], args.images, args.audio,
                                args.resolution, args.duration, not args.no_resize)
        try:
            tid = create_task(workflow_id, payload)
        except RuntimeError as e:
            task["status"] = "failed"
            save_state(state_file, state)
            print(f"    ❌ 提交失败: {e}", flush=True)
            return False
        task["task_id"] = tid
        save_state(state_file, state)
    label = f"#{task.get('num')} {task.get('title')}: " if task.get("num") else ""
    print(f"[2/4] 轮询 {label}task_id={tid}（每 {POLL_INTERVAL}s，最长 {MAX_WAIT//60} 分钟）...")
    try:
        url = poll_task(tid, label)
    except RuntimeError as e:
        task["status"] = "failed"
        save_state(state_file, state)
        log_record({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "task": task.get("title"),
                    "workflow": args.workflow, "resolution": args.resolution,
                    "duration": args.duration, "task_id": tid, "status": "failed",
                    "error": str(e)[:200],
                    "cost_yuan": round(PRICE_PER_SEC.get(res_key(args.resolution), 0) * args.duration, 2),
                    "out": task.get("out")}, log_path)
        print(f"    ❌ {e}", flush=True)
        return False
    out_path = task["out"]
    try:
        download(url, out_path)
    except Exception as e:
        task["status"] = "failed"
        save_state(state_file, state)
        print(f"    ❌ 下载失败: {e}", flush=True)
        return False
    verify = verify_video(out_path, args.duration, args.resolution) if not args.no_verify \
        else {"ok": True, "checks": {"skip": "no-verify"}}
    size_mb = os.path.getsize(out_path) / 1024 / 1024
    cost = PRICE_PER_SEC.get(res_key(args.resolution), 0) * args.duration
    task["status"] = "done"
    save_state(state_file, state)
    log_record({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "task": task.get("title"),
                "workflow": args.workflow, "resolution": args.resolution, "duration": args.duration,
                "task_id": tid, "status": "done", "file_size_mb": round(size_mb, 1),
                "cost_yuan": round(cost, 2), "out": out_path, "verify": verify.get("checks", {})}, log_path)
    mark = "✅" if verify.get("ok") else "⚠️"
    print(f"    {mark} 完成: {out_path} ({size_mb:.1f}MB, 成本≈¥{cost:.2f}) 验收: {verify.get('checks', {})}", flush=True)
    return True


def read_ideas(path: str):
    with open(path, encoding="utf-8") as f:
        lines = f.read().strip().splitlines()
    ideas = []
    i = 0
    while i < len(lines):
        m = re.match(r"^(\d+)[.、]\s*(.+)$", lines[i].strip())
        if m:
            title = m.group(2).strip()
            prompt = lines[i + 1].strip() if i + 1 < len(lines) else ""
            ideas.append({"num": int(m.group(1)), "title": title, "prompt": prompt})
            i += 2
        else:
            i += 1
    return ideas


def main():
    ap = argparse.ArgumentParser(description="AutoDL.Art MiniMax H3 视频生成（单条/批量/断点续传/自动验收）")
    ap.add_argument("-w", "--workflow", default="multi_image", choices=list(WORKFLOWS),
                    help="工作流类型，默认 multi_image")
    ap.add_argument("--prompt", help="提示词（单条模式；批量用 --ideas 文件）")
    ap.add_argument("-i", "--images", action="append", help="参考图片，可多次传")
    ap.add_argument("-a", "--audio", help="参考音频（image_audio/tts 必填）")
    ap.add_argument("-r", "--resolution", default="768p竖", choices=RESOLUTIONS)
    ap.add_argument("-d", "--duration", type=int, default=5, help="秒数：video 1-10，image_audio 1-15")
    ap.add_argument("-o", "--out", default="output.mp4", help="单条输出文件")
    ap.add_argument("--ideas", help="批量选题文件（每项: 编号. 标题 + 下一行提示词）")
    ap.add_argument("--out-prefix", default="video", help="批量输出目录")
    ap.add_argument("--concurrency", type=int, default=10, help="批量并发数（默认10）")
    ap.add_argument("--state", help="状态文件路径（默认自动: 单条={out}.state.json 批量={ideas}.state.json）")
    ap.add_argument("--resume", action="store_true", help="断点续传：已完成跳过、未完成续查、失败重提")
    ap.add_argument("--log", help="JSONL 日志路径（默认输出目录/h3_gen_log.jsonl）")
    ap.add_argument("--no-resize", action="store_true", help="参考图不压缩缩放（原图 base64）")
    ap.add_argument("--no-verify", action="store_true", help="下载后不自动验收")
    args = ap.parse_args()

    load_env_file()

    if args.workflow == "image_audio" and not (args.images and args.audio):
        sys.exit("image_audio 需要 -i 图片 和 -a 音频")
    if args.workflow == "tts" and not (args.audio and args.prompt):
        sys.exit("tts 需要 -a 音频 和 --prompt")
    if args.workflow in ("multi_image", "first_last") and not args.images:
        sys.exit(f"{args.workflow} 需要至少一张 -i 参考图")

    if args.ideas:
        ideas = read_ideas(args.ideas)
        if not ideas:
            sys.exit(f"选题文件为空或格式不对: {args.ideas}")
        print(f"解析到 {len(ideas)} 个选题")
        os.makedirs(args.out_prefix, exist_ok=True)
        state_file = args.state or f"{args.ideas}.state.json"
        state = load_state(state_file)
        tasks = state.setdefault("tasks", {})
        for idea in ideas:
            key = str(idea["num"])
            if key not in tasks:
                tasks[key] = {"num": idea["num"], "title": idea["title"], "prompt": idea["prompt"],
                              "out": os.path.join(args.out_prefix, f"{idea['num']:02d}_{idea['title']}.mp4")}
        log_path = args.log or os.path.join(args.out_prefix, "h3_gen_log.jsonl")
        save_state(state_file, state)
        todo = [t for t in tasks.values() if t.get("status") != "done"]
        if not todo:
            print("全部任务已完成，无需生成")
            return
        print(f"待处理 {len(todo)} 个任务，并发 {args.concurrency}")
        with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
            futs = {ex.submit(run_one, key, t, args, log_path, state, state_file): key
                    for key, t in tasks.items() if t.get("status") != "done"}
            for fut in as_completed(futs):
                try:
                    fut.result()
                except Exception as e:
                    print(f"    ❌ 任务异常: {e}", flush=True)
        done = sum(1 for t in tasks.values() if t.get("status") == "done")
        print(f"批量结束: {done}/{len(tasks)} 完成。状态文件: {state_file}（--resume 可续跑）")
    else:
        if args.workflow in ("multi_image", "first_last", "text2video") and not args.prompt:
            sys.exit(f"{args.workflow} 需要 --prompt")
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        state_file = args.state or f"{args.out}.state.json"
        state = load_state(state_file)
        tasks = state.setdefault("tasks", {})
        key = "single"
        if key not in tasks:
            tasks[key] = {"num": None, "title": os.path.basename(args.out), "prompt": args.prompt or "",
                          "out": args.out}
        save_state(state_file, state)
        log_path = args.log or os.path.join(os.path.dirname(os.path.abspath(args.out)) or ".", "h3_gen_log.jsonl")
        run_one(key, tasks[key], args, log_path, state, state_file)


if __name__ == "__main__":
    main()
