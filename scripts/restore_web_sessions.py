# -*- coding: utf-8 -*-
"""从 OpenClaw 服务端 transcript 重建 Aiyouhu(easel) 前端会话列表 -> web/static/easel-restore.js"""
import sqlite3, shutil, os, tempfile, json, re, datetime, glob

SRC = r"C:\Users\xxx13\.openclaw-easel\agents\main\agent"
PROJ = r"D:\@kaifa\Aiyouhu"
SESSDIR = os.path.join(PROJ, "outputs", "_sessions")

tmp = tempfile.mkdtemp(prefix="ocb_")
for f in ("openclaw-agent.sqlite", "openclaw-agent.sqlite-wal", "openclaw-agent.sqlite-shm"):
    p = os.path.join(SRC, f)
    if os.path.exists(p):
        shutil.copy2(p, os.path.join(tmp, f))
con = sqlite3.connect(os.path.join(tmp, "openclaw-agent.sqlite"))
con.row_factory = sqlite3.Row

# session_id -> session_key
key_of = {}
for r in con.execute("select session_id, session_key, created_at from session_windows"):
    sk = r["session_key"]
    if sk.startswith("agent:main:"):
        key_of.setdefault(r["session_id"], (sk[len("agent:main:"):], r["created_at"]))

rows = list(con.execute(
    "select session_id, role, timestamp, text from session_transcript_fts order by timestamp"))

PERSONA = re.compile(
    r"^我当前使用的画像是「[^」]+」。本会话的账号长期记忆仅使用 [^\n]*?memory\.md[，。]?\s*"
    r"不要使用工作区全局 [A-Z]*MEMORY\.md 作为账号记忆。[^\n]*\n*")

def strip_user(t):
    i = t.find("〔内部提醒")
    if i >= 0:
        t = t[:i]
    t = PERSONA.sub("", t)
    return t.strip()

# ---- 标题生成（store.ts generateSessionTitle 的 Python 移植，简化同构）----
def clean_clause(v):
    v = re.sub(r"^(?:(?:然后|还有|另外|对了|那个|嗯|就是|首先|先说一下|麻烦你?|请问|请你?|能不能|能否|是否可以|可不可以|你能否|你可以|我想(?:要|让你)?|想让你|帮忙|帮我|给我|先|看看|看一下|看下|查一下|查下|确认一下|确认下|我发现|我觉得)[，,、：:\s]*)+", "", v)
    v = re.sub(r"^(?:现在|目前|当前)的?", "", v)
    v = re.sub(r"[吗么呢吧啊呀哦]+[？?！!。.]?$", "", v)
    return v.strip()

def focus_clause(text):
    clauses = [clean_clause(c) for c in re.split(r"[。！？?!；;\n，,]", text)]
    clauses = [c for c in clauses if c]
    if not clauses:
        return text
    dom = re.compile(r"(?:skill|paper-explainer|会话|历史|标题|命名|附件|素材|论文|ppt|slide|视频|字幕|配音|发布|小红书|抖音|图片|模型|配置|项目|页面|前端)", re.I)
    act = re.compile(r"(?:优化|修复|改进|调整|制作|生成|创建|发布|分析|排查|检查)")
    def score(c):
        return (4 if dom.search(c) else 0) + (2 if act.search(c) else 0) - (1 if re.search(r"(?:有可能|是不是|为什么|怎么回事|有点)", c) else 0)
    return max(clauses, key=score)

def title_intent(t):
    if re.search(r"(?:优化|改进|调整|完善|增强|多样|随机)", t): return "optimize"
    if re.search(r"(?:发布|投稿|分发)", t) or re.search(r"(?:上传.*(?:平台|账号|小红书|抖音|B站|bilibili))", t, re.I): return "publish"
    if re.search(r"(?:制作|生成|创建|设计|写一|做一|剪辑|合成)", t): return "create"
    if re.search(r"(?:检查|排查|分析|看看|查看|确认|什么逻辑)", t): return "inspect"
    if re.search(r"(?:bug|修复|解决|问题|异常|报错|失败|卡住|断开|不对|不生效|混乱|拉伸)", t, re.I): return "issue"
    return "general"

def semantic_topic(text, fb):
    m = re.search(r"[「『“\"]([^」』”\"]{2,24})[」』”\"]", text)
    if m and re.search(r"(?:围绕|关于|选题|主题|热点)", text):
        return m.group(1).strip()
    m = re.match(r"^(?:把|将)?(.{2,18}?)(?:发布|投稿|分发)(?:到|至|去|给)", text)
    if m: return m.group(1).strip()
    return None

def gen_title(message):
    text = re.sub(r"```[\s\S]*?```", " ", message)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text: return "新对话"
    text = clean_clause(text)
    base = focus_clause(text)
    base = re.sub(r"^(.+?)配置的?是什么模型$", r"\1模型配置", base)
    base = re.sub(r"^对(.+?)进行", r"\1", base)
    base = base.replace("然后再", "").replace("然后", "").replace("进行", "").replace("这个", "").replace("一下", "")
    base = re.sub(r"(?:怎么|如何|怎样)(?:去)?", "", base)
    base = re.sub(r"(?:是不是|是否|是什么|有哪些|有啥)$", "", base)
    base = re.sub(r"[吗么呢吧啊呀]+$", "", base)
    base = re.sub(r"[，,、：:\s]+$", "", base).strip()
    core = semantic_topic(text, base) or base or "新对话"
    core = core[:18]
    core = re.sub(r"(?:问题排查|故障分析|异常|问题|优化|改进|分析|检查|制作|生成|发布)$", "", core).strip() or "新对话"
    intent = title_intent(text)
    if intent == "issue": t = core + "问题排查"
    elif intent == "create": t = core if re.search(r"(?:文案|脚本|方案)$", core) else core + "制作"
    elif intent == "optimize": t = core + "优化"
    elif intent == "publish": t = core + "发布"
    elif intent == "inspect": t = core + "分析"
    else: t = core
    t = re.sub(r"\S*\.com\S*|\d+\s*@\s*\d+\s*\.\s*\w+\s*:?\s*\d*\s*(?:am|pm)?", " ", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip(" \"'“”-:：")
    if len(t) < 2:
        t = re.sub(r"\s+", " ", message).strip()[:16] or "新对话"
    return t[:24] + "…" if len(t) > 24 else t

# ---- 分组成会话 ----
sessions = {}
for sid in {r["session_id"] for r in rows}:
    if sid not in key_of:
        continue
    fid, created = key_of[sid]
    if fid.startswith("cron:") or fid.startswith("openai:") or fid == "main":
        continue
    sessions[sid] = {"id": fid, "created": created or 0, "turns": []}

cur = {}
for r in rows:
    sid = r["session_id"]
    if sid not in sessions: continue
    role, ts, text = r["role"], r["timestamp"], r["text"]
    if role == "user":
        cur[sid] = {"user": strip_user(text) or text, "u_ts": ts, "ass": []}
        sessions[sid]["turns"].append(cur[sid])
    else:
        if sid in cur: cur[sid]["ass"].append(text)

# web_<id>.json 覆盖末轮终稿
over = 0
for sid, s in sessions.items():
    p = os.path.join(SESSDIR, f"web_{s['id']}.json")
    if os.path.exists(p) and s["turns"]:
        try:
            o = json.load(open(p, encoding="utf-8"))
            if o.get("text"):
                s["turns"][-1]["ass"] = [o["text"]]
                over += 1
        except Exception: pass

out = []
for sid, s in sessions.items():
    msgs = []
    for t in s["turns"]:
        u = (t["user"] or "").strip()
        if u: msgs.append({"role": "user", "content": u})
        ass = [a for a in t["ass"] if a and a.strip()]
        if ass:
            content = ass[-1].strip()
            activity = "\n".join(a.strip() for a in ass[:-1])[:3000]
            m = {"role": "assistant", "content": content}
            if activity: m["activity"] = activity
            msgs.append(m)
    if not msgs: continue
    first_user = next((m["content"] for m in msgs if m["role"] == "user"), "")
    out.append({
        "id": s["id"],
        "title": gen_title(first_user) if first_user else "新对话",
        "messages": msgs,
        "persona": "爱优护电动轮椅软广号" if "爱优护电动轮椅软广号" in "".join(m["content"] for m in msgs[:2]) else None,
        "created": int(s["created"] or s["turns"][0]["u_ts"] or 0),
    })

# 人工校准标题（自动生成的可读性不足）
TITLE_OVERRIDES = {
    "mus2ql90zujohp": "新建技能 fuke·复刻项目",
    "murpyfm0uvpafl": "对标账号拆解·皮皮熊主页",
    "murn5x94ax8ftu": "加油站代金券热点二创",
    "murn4dligs5hkh": "拆解模板二创（空跑）",
    "web-1790986258431": "爆款拆解·加油站代金券",
    "web-1790985821758": "爆款拆解·皮皮熊账号",
    "mur4dgzsc1cy8t": "短剧热点二创软广",
    "mur1akxip0spz9": "微博抖音热搜选题",
    "muqylkulzyl2vw": "广元烟花秀二创软广",
    "muqyknl8ffm9d4": "深夜食堂开头文案",
    "muqyewu2sed0cz": "黄金三秒解释",
    "muqxs3la3utdyy": "职场新人选题（周四发）",
    "muqqm2ef56jghx": "国庆热点二创·带爸妈出行",
    "web-1790931399016": "抖音链接拆解（未完成）",
    "muqq5kaj3lbch4": "国庆热点二创·试跑",
    "web-1790930586572": "画像构建 /skill-profile-builder",
    "muqp87dnuapvj9": "网络修复自检",
}
for s in out:
    s["title"] = TITLE_OVERRIDES.get(s["id"], s["title"])

out.sort(key=lambda s: s["created"], reverse=True)
for s in out:
    if s["persona"] is None: s.pop("persona")

print(f"重建会话 {len(out)} 个，消息 {sum(len(s['messages']) for s in out)} 条，终稿覆盖 {over}")
for s in out:
    print(f"  {s['id']:22s} {datetime.datetime.fromtimestamp(s['created']/1000).strftime('%m-%d %H:%M')} "
          f"msgs={len(s['messages']):3d} persona={'有' if s.get('persona') else '无'} | {s['title']}")

blob = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
js = ("/* Aiyouhu 会话恢复（一次性种子）：从服务端 OpenClaw transcript 重建，2026-10-05 */\n"
      "(function(){try{\n"
      "var GUARD='easel_restore_20261005';\n"
      "if(localStorage.getItem(GUARD))return;\n"
      "try{localStorage.setItem('easel_chat_reset_20260902','1');}catch(e){}\n"  # 阻止前端自带的一次性重置把种子删掉
      "var D=" + blob + ";\n"
      "var cur=[];try{cur=JSON.parse(localStorage.getItem('easel_sessions')||'[]')||[];}catch(e){cur=[];}\n"
      "var have={};D.forEach(function(s){have[s.id]=1;});\n"
      "var keep=cur.filter(function(s){return s&&s.id&&!have[s.id]&&Array.isArray(s.messages)&&s.messages.length>0;});\n"
      "var merged=D.concat(keep);\n"
      "localStorage.setItem('easel_sessions',JSON.stringify(merged));\n"
      "var act=localStorage.getItem('easel_active_session');var found=merged.some(function(s){return s.id===act;});\n"
      "if(!act||!found){localStorage.setItem('easel_active_session',D[0].id);}\n"
      "localStorage.setItem(GUARD,'1');\n"
      "console.log('[easel-restore] 已恢复 '+D.length+' 个会话');\n"
      "}catch(e){console.warn('[easel-restore] 失败',e);}})();\n")

os.makedirs(os.path.join(PROJ, "web", "static"), exist_ok=True)
js_path = os.path.join(PROJ, "web", "static", "easel-restore.js")
open(js_path, "w", encoding="utf-8").write(js)
open(os.path.join(PROJ, "outputs", "_sessions", "_restore_easel_sessions.json"), "w", encoding="utf-8").write(blob)
print("\n写入:", js_path, f"{len(js)} bytes")
print("备份:", os.path.join(PROJ, "outputs", "_sessions", "_restore_easel_sessions.json"))
