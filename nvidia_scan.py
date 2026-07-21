#!/usr/bin/env python3
"""AdventureX 例行扫描 — 纯 NVIDIA 免费档，脱离 Claude。
发现: RSSHub 官方 X + 微博关键词 + 官网/FAQ 页面变更
判级: NVIDIA 免费模型 (deepseek-v4-pro -> glm-5.2 -> nemotron)
推送: botmux send 直发本话题, HIGH @ Max, 每 3h 摘要一次
每 20 分钟由 launchd 触发。运行日志见 scan.log。
"""
import json, os, re, subprocess, sys, urllib.request, xml.etree.ElementTree as ET, hashlib
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
CN = timezone(timedelta(hours=8))
STATE = os.path.join(HERE, "scan_state.json")
FEED_PY = os.path.join(HERE, "feed.py")
FEED_JSON = os.path.join(HERE, "feed.json")
LOG = os.path.join(HERE, "scan.log")

CHAT_ID = "oc_3f3c0c4f9da8dda6480f7a0db87cf9c9"
ROOT_MSG = "om_x100b6ac50e81f0b0c02b9eb3b0a5793"
MAX_OPEN = "ou_98da4571818763404725091bd55328e6"

RSSHUB = "http://localhost:1200"
SOURCES = [
    ("官方 X", f"{RSSHUB}/twitter/user/adventurex_plan"),
    ("微博", f"{RSSHUB}/weibo/keyword/AdventureX"),
]
PAGES = [("官网", "https://adventure-x.org"), ("官方 FAQ", "https://faq.adventure-x.org")]
MODELS = ["deepseek-ai/deepseek-v4-pro", "z-ai/glm-5.2", "nvidia/nemotron-3-super-120b-a12b"]
DIGEST_GAP_H = 3


def log(m):
    line = f"[{datetime.now(CN).isoformat(timespec='seconds')}] {m}"
    with open(LOG, "a") as f:
        f.write(line + "\n")
    print(line)


def load_state():
    if os.path.exists(STATE):
        return json.load(open(STATE))
    return {"page_hashes": {}, "last_digest": None}


def save_state(s):
    json.dump(s, open(STATE, "w"), ensure_ascii=False, indent=2)


def nvidia_key():
    t = open("/Users/max/.openclaw/agents/main/agent/models.json").read()
    return re.findall(r"nvapi-[A-Za-z0-9_-]+", t)[0]


UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")


def strip(html):
    return re.sub(r"<[^>]+>", "", html or "").strip()


def gather_candidates(state):
    """返回 [{title,url,source,snippet}]"""
    cands = []
    for name, url in SOURCES:
        try:
            root = ET.fromstring(fetch(url))
            for it in root.iter("item"):
                title = strip(it.findtext("title") or "")
                link = (it.findtext("link") or "").strip()
                desc = strip(it.findtext("description") or "")[:280]
                if title or desc:
                    cands.append({"title": title or desc[:60], "url": link,
                                  "source": name, "snippet": desc})
        except Exception as e:
            log(f"source {name} failed: {e}")
    # 页面变更探测: hash 变了就丢一个候选让模型判要不要看
    for name, url in PAGES:
        try:
            txt = strip(fetch(url))
            h = hashlib.sha1(txt.encode()).hexdigest()[:12]
            old = state["page_hashes"].get(url)
            if old and old != h:
                cands.append({"title": f"{name} 页面内容有更新", "url": url,
                              "source": name, "snippet": "官方页面自上次扫描后发生变化，可能是新公告/嘉宾/日程。"})
            state["page_hashes"][url] = h
        except Exception as e:
            log(f"page {name} failed: {e}")
    return cands


def existing_keys():
    if not os.path.exists(FEED_JSON):
        return set()
    return {it["id"] for it in json.load(open(FEED_JSON))}


def key_of(url, title):
    basis = (url or "").strip().lower() + "|" + title.strip().lower()
    return hashlib.sha1(basis.encode()).hexdigest()[:12]


def classify(cands, key):
    """一次调用给所有候选判级。返回 [{index,tier,summary,tag}] , tier in HIGH/MEDIUM/DROP"""
    ctx = (
        "你是 AdventureX 2026 黑客松(2026-07-22至26,杭州)的信息哨兵,为【已录取的参赛者 Max】过滤消息。\n"
        "已知基本盘(别当新闻,一律DROP): 时间地点/主题「为创造再一次信仰之跃」/800+人/$150K奖金/官网/报名已开放/录取通知。\n"
        "判级红线(从严):\n"
        "HIGH(值得立刻打扰他,极少)= 只有这几类: ①开幕或主题演讲【嘉宾/speaker/keynote】名单公布 ②日程/场地/签到/报到规则的【变动或硬通知】 ③Max能报名参加的【具体环节】(workshop/side event/名额/截止时间) ④直接影响他行程或参赛资格的硬信息。\n"
        "MEDIUM= 合作伙伴/赞助商公布(partner/sponsor,哪怕写exclusive)、有用的社区讨论/攻略/工具/周边动态、非关键官方小更新。\n"
        "DROP= 已知基本盘、报名开放/录取类旧推(他已录取)、路人打卡、蹭词营销、纯转发、2025及更早旧闻、无实质内容。判定要狠,拿不准就DROP。\n"
        "注意: 合作伙伴公布不是嘉宾公布,一律MEDIUM不是HIGH。\n"
        "对每条候选输出: tier(HIGH/MEDIUM/DROP)、title(干净的中文短标题,≤22字,别抄英文原文)、summary(一句中文说清是什么为什么重要,≤40字)、tag(嘉宾/日程/签到/媒体/社区/周边 之一)。\n"
        "只输出 JSON 数组,每项 {\"index\":序号,\"tier\":\"..\",\"title\":\"..\",\"summary\":\"..\",\"tag\":\"..\"},不要多余文字。"
    )
    items = "\n".join(f'{i}. [{c["source"]}] {c["title"]} — {c["snippet"][:160]}'
                      for i, c in enumerate(cands))
    payload = {"messages": [{"role": "system", "content": ctx},
                            {"role": "user", "content": "候选:\n" + items}],
               "temperature": 0, "max_tokens": 1500}
    for model in MODELS:
        try:
            body = dict(payload, model=model)
            req = urllib.request.Request(
                "https://integrate.api.nvidia.com/v1/chat/completions",
                data=json.dumps(body).encode(),
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
            resp = json.load(urllib.request.urlopen(req, timeout=120))
            txt = resp["choices"][0]["message"]["content"]
            txt = re.sub(r"^```(json)?|```$", "", txt.strip(), flags=re.M).strip()
            m = re.search(r"\[.*\]", txt, re.S)
            arr = json.loads(m.group(0) if m else txt)
            log(f"classified via {model}: {len(arr)} verdicts")
            return arr
        except Exception as e:
            log(f"model {model} failed: {e}")
    return []


def feed_add(tier, title, url, source, summary, tag):
    if DRY:
        log(f"[DRY] would add {tier} [{tag}] {title} :: {summary}")
        return
    subprocess.run([sys.executable, FEED_PY, "add", "--tier", tier, "--title", title,
                    "--url", url, "--source", source, "--summary", summary, "--tag", tag],
                   check=False)


DRY = os.environ.get("DRY") == "1"        # 纯预览: 不写不推不提交
NOSEND = os.environ.get("NOSEND") == "1"  # 铺底: 写入库+看板,但不推飞书


def send(text, mention=False):
    if DRY or NOSEND:
        log(f"[{'DRY' if DRY else 'NOSEND'}] suppressed send (mention={mention}):\n{text[:400]}")
        return
    cmd = ["botmux", "send", "--chat-id", CHAT_ID, "--root-msg-id", ROOT_MSG]
    cmd += (["--mention", MAX_OPEN] if mention else ["--no-mention"])
    subprocess.run(cmd, input=text, text=True, check=False)


def git_push():
    if DRY:
        return
    for c in (["git", "add", "feed.json"],
              ["git", "commit", "-q", "-m", f"scan {datetime.now(CN):%m-%d %H:%M}"],
              ["git", "push", "-q"]):
        subprocess.run(c, cwd=HERE, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def maybe_digest(state):
    last = state.get("last_digest")
    if last:
        gap = (datetime.now(CN) - datetime.fromisoformat(last)).total_seconds() / 3600
        if gap < DIGEST_GAP_H:
            return
    out = subprocess.run([sys.executable, FEED_PY, "pending"], capture_output=True, text=True)
    pending = json.loads(out.stdout or "[]")
    if not pending:
        state["last_digest"] = datetime.now(CN).isoformat(timespec="seconds")
        return
    lines = [f"🟡 AdventureX 这几小时的动态（{len(pending)} 条）", ""]
    for p in pending:
        lines.append(f"• {p['title']} — {p['summary']}" + (f"\n  {p['url']}" if p["url"] else ""))
    lines += ["", "重要的都已即时推过，这些是次要动静。"]
    send("\n".join(lines), mention=False)
    subprocess.run([sys.executable, FEED_PY, "mark-digested"], check=False)
    state["last_digest"] = datetime.now(CN).isoformat(timespec="seconds")
    log(f"digest sent: {len(pending)} items")


def main():
    state = load_state()
    key = nvidia_key()
    cands = gather_candidates(state)
    dropped = set(state.get("dropped", []))
    seen = existing_keys() | dropped
    fresh = [c for c in cands if key_of(c["url"], c["title"]) not in seen]
    fresh = fresh[:12]  # RSS 已按时间倒序,只判最新一批,控住判级延迟
    log(f"candidates={len(cands)} fresh={len(fresh)}")

    highs = []
    if fresh:
        verdicts = classify(fresh, key)
        for v in verdicts:
            try:
                c = fresh[int(v["index"])]
            except (KeyError, ValueError, IndexError):
                continue
            tier = str(v.get("tier", "DROP")).upper()
            if tier not in ("HIGH", "MEDIUM"):
                dropped.add(key_of(c["url"], c["title"]))  # 记住已判定为噪音,别反复重判
                continue
            title = (v.get("title") or c["title"])[:40]
            summary, tag = v.get("summary", ""), v.get("tag", "")
            feed_add(tier, title, c["url"], c["source"], summary, tag)
            if tier == "HIGH":
                highs.append((c, title, summary, tag))

    if highs:
        lines = ["🔴 AdventureX 重要动态", ""]
        for c, title, s, tag in highs:
            lines.append(f"【{c['source']}·{tag}】{title}\n{s}" + (f"\n{c['url']}" if c["url"] else ""))
            lines.append("")
        send("\n".join(lines), mention=True)
        log(f"pushed {len(highs)} HIGH")

    state["dropped"] = list(dropped)[-800:]  # 上限,防无限增长
    maybe_digest(state)
    save_state(state)
    git_push()
    log("done")


if __name__ == "__main__":
    main()
