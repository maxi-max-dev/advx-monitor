#!/usr/bin/env python3
"""AdventureX monitor feed store. Dedup + tiered push state.
Usage:
  feed.py add --tier HIGH|MEDIUM --title T [--url U] [--source S] [--summary D] [--tag TAG]
  feed.py pending          # print MEDIUM items not yet digested (JSON), does NOT mark
  feed.py mark-digested    # mark all pending -> digested
  feed.py stats            # counts
"""
import json, sys, os, hashlib, argparse
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
FEED = os.path.join(HERE, "feed.json")
CN = timezone(timedelta(hours=8))


def load():
    if not os.path.exists(FEED):
        return []
    with open(FEED) as f:
        return json.load(f)


def save(items):
    with open(FEED, "w") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def key_of(url, title):
    # dedup on url+title: same page re-found with same title = dup;
    # multiple distinct facts sharing a base domain stay separate.
    basis = (url or "").strip().lower() + "|" + title.strip().lower()
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]


def cmd_add(a):
    items = load()
    # 优先用显式传入的稳定 key(锚定原始候选),否则回退到 url+title
    k = a.key if getattr(a, "key", None) else key_of(a.url, a.title)
    if any(it["id"] == k for it in items):
        print("dup")
        return
    now = datetime.now(CN).isoformat(timespec="seconds")
    items.append({
        "id": k,
        "ts": now,
        "tier": a.tier.upper(),
        "title": a.title.strip(),
        "summary": (a.summary or "").strip(),
        "url": (a.url or "").strip(),
        "source": (a.source or "").strip(),
        "tag": (a.tag or "").strip(),
        # HIGH is pushed instantly by the session; MEDIUM waits for the digest
        "pushed": "now" if a.tier.upper() == "HIGH" else "pending",
    })
    save(items)
    print("added")


def cmd_pending(a):
    items = load()
    p = [it for it in items if it.get("pushed") == "pending"]
    print(json.dumps(p, ensure_ascii=False, indent=2))


def cmd_mark(a):
    items = load()
    n = 0
    for it in items:
        if it.get("pushed") == "pending":
            it["pushed"] = "digested"
            n += 1
    save(items)
    print(f"marked {n}")


def cmd_stats(a):
    items = load()
    hi = sum(1 for i in items if i["tier"] == "HIGH")
    med = sum(1 for i in items if i["tier"] == "MEDIUM")
    pend = sum(1 for i in items if i.get("pushed") == "pending")
    print(f"total={len(items)} high={hi} medium={med} pending={pend}")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("--tier", required=True)
    a.add_argument("--title", required=True)
    a.add_argument("--url", default="")
    a.add_argument("--source", default="")
    a.add_argument("--summary", default="")
    a.add_argument("--tag", default="")
    a.add_argument("--key", default="")
    sub.add_parser("pending")
    sub.add_parser("mark-digested")
    sub.add_parser("stats")
    args = p.parse_args()
    {"add": cmd_add, "pending": cmd_pending,
     "mark-digested": cmd_mark, "stats": cmd_stats}[args.cmd](args)


if __name__ == "__main__":
    main()
