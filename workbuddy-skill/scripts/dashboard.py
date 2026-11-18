# -*- coding: utf-8 -*-
"""看板的计算和出图。beike.py 看 把飞书几张表拉下来交给这里，这里不连网、不碰凭证。

    compute(成绩行, 名单, 单元行, 词表行) → 一个 dict（每个单元一份）
    render_html(模型)  → 单文件网页（数据烧在页面里，不连任何外部地址）
    summary_text(模型) → 一段能直接发微信的文字
    wrong_words_md(模型) → 易错词榜 Markdown（可以存进 ima）

几条口径（和 collect.py 一致的地方不再解释）：
- 谁交了：按（班级, 姓名）对，不按名字对。
- 易错词：只看每个人的**第一次**。反复做的人刷到全对，不代表第一次就会；也避免一个人被数好几遍。
- 每个学生的四个数：看**最近一次**，同时给出第一次 → 最近一次的「对了」。
- 四个数加起来应该等于这个单元的题数；对不上的单独列出来（多半是旧版网页交的，或者表里被手改过）。
"""
import html, json, re
from collections import OrderedDict, defaultdict
from datetime import datetime

STATES = ["对了", "差一点", "还不会", "待老师看"]
WORD_RE = re.compile(r"[A-Za-z][A-Za-z '\-]*")


def num(x, d=0):
    try:
        return int(float(str(x).strip()))
    except (TypeError, ValueError):
        return d


def split_list(s):
    return [x.strip() for x in re.split(r"[、,，]", str(s or "")) if x.strip()]


def mmss(sec):
    sec = num(sec)
    return f"{sec // 60}分{sec % 60:02d}秒" if sec >= 60 else f"{sec}秒"


def is_review(pid):
    """「我的复习」交上来的（review-日期）：算进每个人的学情，但不单独占一个课的分页。"""
    return str(pid).startswith("review-")


def normalize_units(records, units, catalog=None):
    """单元表可能没有（老 base），也可能缺几个单元：从成绩里补。题数取四个数之和最常见的那个值。
    有课目录（catalog，archive.catalog 的格式）时按课目录的第几课排，和学生页的分页一致；课目录里没有的排在后面。"""
    out = OrderedDict()
    for u in sorted(units, key=lambda u: (num(u.get("顺序"), 999), str(u.get("发布时间") or ""))):
        pid = str(u.get("内容包") or "").strip()
        if pid and not is_review(pid):
            out[pid] = {"id": pid, "title": u.get("标题") or pid, "n": num(u.get("题数")),
                        "date": str(u.get("发布时间") or "")[:10], "from_table": True}
    sums = defaultdict(lambda: defaultdict(int))
    for r in records:
        pid = r["内容包"]
        if is_review(pid):
            continue
        sums[pid][sum(num(r.get(k)) for k in STATES)] += 1
        if pid not in out:
            m = re.search(r"(\d{8})$", pid)
            out[pid] = {"id": pid, "title": pid, "n": 0,
                        "date": f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]}" if m else "",
                        "from_table": False}
    for pid, u in out.items():
        if not u["n"] and sums[pid]:
            u["n"] = max(sums[pid].items(), key=lambda x: x[1])[0]
            u["n_guessed"] = True
    # 没有单元表时按日期排
    if not any(u["from_table"] for u in out.values()):
        out = OrderedDict(sorted(out.items(), key=lambda x: x[1]["date"]))
    if catalog:
        ordered = OrderedDict()
        for e in sorted(catalog, key=lambda e: num(e.get("n"), 999)):
            pid = str(e.get("packId") or "")
            if not pid or is_review(pid) or e.get("kind") == "复习":
                continue
            u = out.pop(pid, None) or {"id": pid, "title": pid, "n": 0, "date": "", "from_table": False}
            u["title"] = e.get("title") or u["title"]
            u["date"] = u["date"] or str(e.get("date") or "")[:10]
            u.update(lesson=num(e.get("n")) or None, hidden=bool(e.get("hidden")), kind=e.get("kind") or "课")
            ordered[pid] = u
        ordered.update(out)
        out = ordered
    return out


def compute(records, roster, units=(), words=(), meta=None, catalog=None, learn=None, plan=None, archived=(),
            expected=None):
    """records: 成绩表每行一个 dict；roster: OrderedDict{班级: [姓名]}；units/words: 单元表、词表的行。
    下面几个都可以不给（不给就和以前一样）：
    catalog：课目录 [{n, packId, title, date, hidden, kind}]（archive.catalog），决定课的顺序和「第几课」；
    learn：learning.compute 的结果原样给（每个学生每个词拿下没有），这里只挑出来放进页面，不重算；
    plan：复习计划.json 的内容（learning.load_plan）；archived：已经收尾（有存档.md）的 packId；
    expected：{packId: [班·名…]}，期末那种按人出词的课只有这些人应该交（没有自己词的人不算没交）。"""
    meta = dict(meta or {})
    recs = []
    for r in records:
        r = {k: ("" if v is None else v) for k, v in r.items()}
        if not str(r.get("姓名", "")).strip() or not str(r.get("内容包", "")).strip():
            continue
        r["班级"], r["姓名"], r["内容包"] = (str(r.get(k, "")).strip() for k in ("班级", "姓名", "内容包"))
        r["第几次"] = num(r.get("第几次"), 1) or 1
        recs.append(r)
    U = normalize_units(recs, list(units), catalog)
    vocab = defaultdict(list)
    for w in words:
        pid = str(w.get("内容包") or "").strip()
        if pid and w.get("词"):
            vocab[pid].append({"w": str(w["词"]).strip(), "zh": str(w.get("中文") or ""),
                               "src": str(w.get("来源") or "本单元")})
    zh_of = {v["w"].lower(): v["zh"] for vs in vocab.values() for v in vs if v["zh"]}
    classes = list(roster.keys())
    known = {(c, n) for c, ns in roster.items() for n in ns}

    by_unit = defaultdict(list)
    for r in recs:
        by_unit[r["内容包"]].append(r)

    def first_latest(rows):
        first, latest, tries = {}, {}, defaultdict(list)
        for r in rows:
            k = (r["班级"], r["姓名"])
            tries[k].append(r)
        for k, rs in tries.items():
            rs.sort(key=lambda r: r["第几次"])
            first[k], latest[k] = rs[0], rs[-1]
        return first, latest, tries

    no_roster = bool(meta.get("no_roster"))       # 没有名单：只能说谁交了，说不了谁没交
    full_roster = roster
    unit_out, firsts = [], {}
    for pid, u in U.items():
        rows = by_unit.get(pid, [])
        first, latest, tries = first_latest(rows)
        if no_roster:
            roster = OrderedDict((c, [x for (cc, x) in latest if cc == c]) for c in classes)
        firsts[pid] = first
        n = u["n"]
        exp = (expected or {}).get(pid)
        per_person = exp is not None or (u.get("kind") or "课") != "课"     # 期末：每人的词不一样，题数也不一样
        R = roster if exp is None else OrderedDict((c, [x for x in roster[c] if f"{c}·{x}" in set(exp)]) for c in classes)
        # ── 交作业
        cls_out = []
        for c in classes:
            ns = R[c]
            done = [x for x in ns if (c, x) in latest]
            miss = [x for x in ns if (c, x) not in latest]
            cls_out.append({"cls": c, "total": len(ns), "done": len(done), "missing": miss})
        unknown = sorted({f"{c}·{x}" for (c, x) in latest if (c, x) not in known})
        # ── 每个学生
        students, mismatch = [], []
        for c in classes:
            for x in R[c]:
                k = (c, x)
                if k not in latest:
                    students.append({"cls": c, "name": x, "done": False})
                    continue
                L, F = latest[k], first[k]
                counts = [num(L.get(s)) for s in STATES]
                fast = [t["第几次"] for t in tries[k] if str(t.get("用时偏短", "")).strip() == "是"]
                st = {"cls": c, "name": x, "done": True, "counts": counts, "sum": sum(counts),
                      "tries": len(tries[k]), "first_right": num(F.get("对了")), "last_right": counts[0],
                      "secs": num(L.get("用时秒")), "fast": fast, "self": str(L.get("自评") or ""),
                      "nope": split_list(L.get("还不会清单")), "shaky": split_list(L.get("差一点清单")),
                      "last_fast": str(L.get("用时偏短", "")).strip() == "是"}
                if n and st["sum"] != n and not per_person:
                    mismatch.append(f"{c}·{x}（{st['sum']} ≠ {n}）")
                students.append(st)
        for k in latest:
            if k not in known:
                L = latest[k]
                counts = [num(L.get(s)) for s in STATES]
                students.append({"cls": k[0], "name": k[1], "done": True, "unknown": True, "counts": counts,
                                 "sum": sum(counts), "tries": len(tries[k]), "first_right": num(first[k].get("对了")),
                                 "last_right": counts[0], "secs": num(L.get("用时秒")), "fast": [],
                                 "self": str(L.get("自评") or ""), "nope": split_list(L.get("还不会清单")),
                                 "shaky": split_list(L.get("差一点清单"))})
        # ── 要老师亲自看（看最近一次；用时偏短看每一次）
        attention = []
        for s in students:
            if not s["done"]:
                continue
            why = []
            if s["counts"][2] >= 5:
                why.append(f"{s['counts'][2]} 个还不会")
            if s["fast"]:
                t = tries[(s["cls"], s["name"])]
                f0 = next(r for r in t if r["第几次"] == s["fast"][0])
                why.append(f"第{s['fast'][0]}次只用了 {mmss(f0.get('用时秒'))}，可能是乱点的")
            if s["self"] == "我还不会":
                why.append("自己说还不会")
            elif s["self"] == "会了" and s["counts"][2] >= 4 and not s["fast"]:
                why.append(f"自评会了，其实 {s['counts'][2]} 个还不会")
            if why:
                attention.append({"cls": s["cls"], "name": s["name"], "why": why,
                                  "score": s["counts"][2] + 4 * bool(s["fast"])})
        attention.sort(key=lambda a: -a["score"])
        compose = sum(1 for s in students if s["done"] and s["counts"][3] > 0)
        # ── 易错（第一次）
        agg = {}
        for k, F in first.items():
            nope, shaky = split_list(F.get("还不会清单")), split_list(F.get("差一点清单"))
            for lab in dict.fromkeys(nope + shaky):
                a = agg.setdefault(lab, {"item": lab, "nope": 0, "shaky": 0, "by": defaultdict(int)})
                if lab in nope:
                    a["nope"] += 1
                else:
                    a["shaky"] += 1
                a["by"][k[0]] += 1
        wrong = sorted(agg.values(), key=lambda a: (-(2 * a["nope"] + a["shaky"]), a["item"]))
        for a in wrong:
            a["people"] = a["nope"] + a["shaky"]
            a["by"] = dict(a["by"])
            a["is_word"] = bool(WORD_RE.fullmatch(a["item"]))
            a["zh"] = zh_of.get(a["item"].lower(), "")
        # ── 本单元的复习词
        review_words = [v for v in vocab.get(pid, []) if v["src"].startswith("复习")]
        right_rate = [s["counts"][0] / max(1, s["sum"] - s["counts"][3]) for s in students if s["done"] and not s.get("unknown")]
        unit_out.append({
            "id": pid, "title": u["title"], "date": u["date"], "n": n, "n_guessed": u.get("n_guessed", False),
            "lesson": u.get("lesson"), "hidden": u.get("hidden", False), "kind": u.get("kind", "课"),
            "per_person": per_person,
            "archived": pid in set(archived or ()),
            "classes": cls_out, "unknown": unknown, "students": students, "mismatch": mismatch,
            "attention": attention, "compose": compose, "wrong": wrong[:80],
            "submissions": len(rows), "repeaters": sum(1 for t in tries.values() if len(t) > 1),
            "review_words": [v["w"] for v in review_words],
            "avg_right": round(100 * sum(right_rate) / len(right_rate)) if right_rate else None,
            "class_right": {c: _avg([s for s in students if s["cls"] == c and s["done"]]) for c in classes},
        })

    # ── 几个单元下来：错词有没有复习回来
    ids = list(U.keys())
    recovery = []
    for bi, pid in enumerate(ids):
        for v in vocab.get(pid, []):
            if not v["src"].startswith("复习"):
                continue
            w = v["w"]
            src_pid = None
            for ai in range(bi - 1, -1, -1):          # 最近一个有人错过这个词的单元
                if any(w in split_list(F.get("还不会清单")) + split_list(F.get("差一点清单"))
                       for F in firsts[ids[ai]].values()):
                    src_pid = ids[ai]
                    break
            if not src_pid:
                continue
            before = [k for k, F in firsts[src_pid].items()
                      if w in split_list(F.get("还不会清单")) + split_list(F.get("差一点清单"))]
            got, still, skip = [], [], []
            for k in before:
                F = firsts[pid].get(k)
                if not F:
                    skip.append(k)
                elif w in split_list(F.get("还不会清单")) + split_list(F.get("差一点清单")):
                    still.append(k)
                else:
                    got.append(k)
            recovery.append({"word": w, "zh": v["zh"] or zh_of.get(w.lower(), ""), "from": U[src_pid]["title"],
                             "to": U[pid]["title"], "to_id": pid, "before": len(before), "got": len(got),
                             "still": [f"{c}·{x}" for c, x in still], "skip": len(skip),
                             "got_who": [f"{c}·{x}" for c, x in got]})
    reviewed = {(r["word"].lower()) for r in recovery}
    not_reviewed = []
    for u in unit_out[:-1]:                          # 最新一个单元的错词还没机会复习，不算
        for a in u["wrong"]:
            if a["is_word"] and a["item"].lower() not in reviewed and a["people"] >= 5:
                later = [x for x in ids[ids.index(u["id"]) + 1:]
                         if any(v["w"].lower() == a["item"].lower() for v in vocab.get(x, []))]
                if not later:
                    not_reviewed.append({"word": a["item"], "zh": a["zh"], "unit": u["title"], "people": a["people"]})
    not_reviewed.sort(key=lambda x: -x["people"])

    # ── 趋势：每个班每个单元
    trend = []
    for c in classes:
        row = {"cls": c, "units": []}
        for u in unit_out:
            cc = next(x for x in u["classes"] if x["cls"] == c)
            row["units"].append({"id": u["id"], "rate": None if no_roster else round(100 * cc["done"] / max(1, cc["total"])),
                                 "right": u["class_right"].get(c)})
        trend.append(row)
    # 连续两个单元都没交的人（最新单元不算，刚发）
    roster = full_roster
    chronic = []
    if len(unit_out) >= 3 and not no_roster:
        a, b = unit_out[-3], unit_out[-2]
        for c in classes:
            ma = set(next(x for x in a["classes"] if x["cls"] == c)["missing"])
            mb = set(next(x for x in b["classes"] if x["cls"] == c)["missing"])
            chronic += [f"{c}·{x}" for x in roster[c] if x in ma and x in mb]

    meta.setdefault("generated", datetime.now().strftime("%Y-%m-%d %H:%M"))
    meta["has_units_table"] = bool(units)
    meta["has_words_table"] = bool(words)
    meta["has_catalog"] = bool(catalog)
    names = {u["id"]: (f"第{u['lesson']}课" if u.get("lesson") else u["title"]) for u in unit_out}
    for e in catalog or ():
        names.setdefault(e.get("packId"), f"第{num(e.get('n'))}课" if num(e.get("n")) else e.get("title"))
    lm, zh_more = learn_view(learn)
    # 「我的复习」交了几轮（每轮第一份不偏短的才算），宠物给豆子用
    reviews = defaultdict(set)
    for r in recs:
        if is_review(r["内容包"]) and str(r.get("用时偏短", "")).strip() != "是":
            reviews[f"{r['班级']}·{r['姓名']}"].add(r["内容包"])
    zh_all = dict(zh_more)
    zh_all.update({k: v for k, v in ((plan or {}).get("中文") or {}).items() if v})
    zh_all.update({v["w"]: v["zh"] for vs in vocab.values() for v in vs if v["zh"]})
    return {"meta": meta, "classes": classes, "roster_total": sum(len(v) for v in roster.values()),
            "units": unit_out, "recovery": recovery, "not_reviewed": not_reviewed[:12],
            "trend": trend, "chronic": chronic, "names": names,
            "learn": lm, "plan": plan_view(plan), "zh": zh_all,
            "reviews": {k: sorted(v) for k, v in reviews.items()}}


def _key(k):
    return k if isinstance(k, str) else "·".join(k)


def learn_view(learn):
    """learning.compute 的结果 → {学生键: {"got": [词…], "doing": [[词, 还不会/差一点, [错在哪几课…]]…]}}。
    只是挑出来，不改任何一个数。没给就是 None（页面上不出这一块）。"""
    if not learn:
        return None, {}
    out = {}
    for k, ws in (learn.get("学生") or {}).items():
        got = sorted(w for w, s in ws.items() if s.get("状态") == "拿下")
        doing = [[w, s.get("状态"), list(s.get("错在哪几课") or [])] for w, s in ws.items() if s.get("状态") != "拿下"]
        doing.sort(key=lambda x: (-len(x[2]), x[1] != "还不会", x[0]))
        if got or doing:
            out[_key(k)] = {"got": got, "doing": doing}
    return out, learn.get("中文") or {}


# learning.draft_plan 现在只写「已排好」「关掉」；「草稿」「已确认」「已用」是老文件里的，照「已排好」说。
# 配了 review_api（妙搭后端）时，「我的复习」是学生点开时现查的；没配才是发新课时写进网页。
PLAN_SAYS = {"已排好": {True: "系统按每个人没拿下的词排好了，学生点开「我的复习」时现查，交了作业就跟着变，不用你确认",
                       False: "系统按每个人没拿下的词排好了，下次发新课时每个人的「我的复习」就是这些，不用你确认"},
             "关掉": {True: "你说过这次不带复习：下次发的那一课不放「我的复习」，发完自动恢复，不用再说什么",
                      False: "你说过这次不带复习：下次发的那一课不放「我的复习」，发完自动恢复，不用再说什么"}}


def plan_view(p):
    """复习计划.json → 页面上那一块要的东西。读不懂的字段就当没有，不报错。"""
    if not isinstance(p, dict):
        return None
    st = "关掉" if p.get("状态") == "关掉" else "已排好"
    live = bool(p.get("_现查"))
    per = {k: list(v) for k, v in (p.get("每人") or {}).items() if isinstance(v, (list, tuple)) and v}
    most = sorted(per.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:8]
    return {"state": st, "says": PLAN_SAYS[st][live], "live": live,
            "made": str(p.get("生成于") or ""), "from": str(p.get("来自") or ""), "for": str(p.get("这一课") or ""),
            "used_in": str(p.get("用在") or ""), "class": [str(w) for w in (p.get("全班") or [])],
            "dropped": [str(w) for w in (p.get("去掉") or [])], "added": [str(w) for w in (p.get("加上") or [])],
            "per": per, "people": len(per), "total": sum(len(v) for v in per.values()),
            "back": p.get("上次拿下") if isinstance(p.get("上次拿下"), int) else None,
            "most": [[k, len(v)] for k, v in most]}


def _avg(ss):
    xs = [s["counts"][0] / max(1, s["sum"] - s["counts"][3]) for s in ss if s.get("sum")]
    return round(100 * sum(xs) / len(xs)) if xs else None


# ── 输出 ─────────────────────────────────────────────
def render_html(model, template):
    data = json.dumps(model, ensure_ascii=False).replace("</", "<\\/").replace("<!--", "<\\u0021--")
    title = "背单词闯关看板" + ("（演示数据）" if model["meta"].get("demo") else "")
    return template.replace("{{TITLE}}", html.escape(title)).replace("{{DATA}}", data)


def default_unit(model):
    """默认看哪一课：最近一课有人交了的、没撤的（和看板网页一样）。"""
    us = model["units"]
    return next((u for u in reversed(us) if not u.get("hidden") and any(c["done"] for c in u["classes"])), us[-1])


def overall(model, u):
    """全班整体（看板第一屏和摘要共用）：交了多少、整体对了多少、和上一课比、全班卡在哪几个词、
    上次的错词复习回来了多少、造句有几条等看。只有数，不带名字。"""
    us = model["units"]
    no_roster = model["meta"].get("no_roster")
    done = lambda x: sum(c["done"] for c in x["classes"])
    total = lambda x: sum(c["total"] for c in x["classes"])
    rate = lambda x: None if no_roster else round(100 * done(x) / max(1, total(x)))
    i = us.index(u)
    lesson = lambda x: (x.get("kind") or "课") == "课"
    prev = next((x for x in reversed(us[:i]) if not x.get("hidden") and lesson(x) and done(x)), None) if lesson(u) else None
    pl = model.get("plan") or {}
    miss = [len(c["missing"]) for c in u["classes"]]
    return {"name": model["names"].get(u["id"], u["title"]), "done": done(u), "total": total(u), "rate": rate(u),
            "right": u["avg_right"],
            "prev": prev and {"name": model["names"].get(prev["id"], prev["title"]), "rate": rate(prev),
                              "right": prev["avg_right"]},
            "words": [[a["item"], a["zh"], a["people"]] for a in u["wrong"] if a["is_word"]][:5],
            "back": pl.get("back"), "missing": sum(miss), "per_person": u.get("per_person", False),
            "compose": sum(1 for s in u["students"] if s["done"] and s["counts"][3] > 0),
            "unknown": len(u["unknown"])}


def pets_view(pm, page):
    """宠物墙算出来的东西 → 看板要的：整页宠物墙（放进「宠物」页签）、每个学生一行（搜名字时看）、全班整体的几个数。"""
    sp = [s["kind"] + s["zh"] for s in pm["species"]]
    by = {p["key"]: {"sp": "一颗蛋" if p["stage"] == 0 else sp[p["sp"]] + "·" + pm["stages"][p["stage"]], "earned": p["earned"],
                     "balance": p["balance"], "next": p["next"], "own": len(p["own"])} for p in pm["pets"]}
    counts = [sum(1 for p in pm["pets"] if p["stage"] == i) for i in range(len(pm["stages"]))]
    return {"html": page, "by": by, "stages": pm["stages"], "counts": counts, "total": len(pm["pets"]),
            "hatched": len(pm["changes"]["hatched"]), "grew": len(pm["changes"]["grew"]),
            "first_run": pm.get("first_run", False),
            "scenes": {c: [x["zh"] for x in v["have"]] for c, v in pm["scenes"].items()}}


def _vs(now, before, name):
    if now is None or before is None:
        return ""
    d = now - before
    return f"，比{name}{'高' if d > 0 else '低'} {abs(d)} 个百分点" if d else f"，和{name}一样"


def summary_text(model, unit_id=None):
    """「看 --摘要」和「看」的输出：只讲全班整体，不列名字。每个人的情况在看板里搜名字看。默认说最近一课。"""
    if not model["units"]:
        return "成绩表里还没有提交。"
    u = next((x for x in model["units"] if x["id"] == unit_id), None) or default_unit(model)
    m, o = model["meta"], overall(model, u)
    P = o["prev"]
    lines = [f"【背单词闯关】{m.get('generated', '')}" + ("（演示数据）" if m.get("demo") else ""),
             f"{o['name']} {u['title']}" + (f"（{u['date']} 发）" if u["date"] else "")]
    if m.get("no_roster"):
        lines.append(f"交了 {o['done']} 人。还没有名单，算不出交了几成（把名单给 WorkBuddy 存一次就行）。")
    else:
        lines.append(f"交了 {o['done']}/{o['total']} 人（{o['rate']}%）" + _vs(o["rate"], P and P["rate"], P and P["name"]) + "。"
                     + "各班：" + "、".join(f"{c['cls'].replace('高一', '')} {c['done']}/{c['total']}" for c in u["classes"]) + "。"
                     + ("（期末课：只算有自己复习词的人。）" if o["per_person"] else ""))
        lines.append(f"没交 {o['missing']} 人，名单在看板上（第一屏「每个班谁交了、谁没交」）。" if o["missing"] else "全交了。")
    if o["right"] is not None:
        lines.append(f"整体对了 {o['right']}%" + _vs(o["right"], P and P["right"], P and P["name"]) + "。")
    if o["words"]:
        lines.append("全班卡在（适合课上讲）：" + "、".join(f"{w} {n}人" for w, _, n in o["words"]) + "。")
    pl = model.get("plan")
    if pl and pl["state"] == "关掉":
        lines.append("复习情况：你说过这次不带复习，下次发的那一课不放「我的复习」，发完自动恢复。")
    elif pl:
        lines.append("复习情况：" + (f"系统给 {pl['people']} 人排了自己的复习，平均每人 {pl['total'] / pl['people']:.0f} 个词"
                                    if pl["people"] else "这次没有人需要自己复习")
                     + (f"；上一轮排的词，这一轮拿下了 {pl['back']} 个" if pl.get("back") is not None else "")
                     + (f"；全班去掉了 {'、'.join(pl['dropped'])}" if pl["dropped"] else "") + "。不用你确认。")
    if o["compose"]:
        lines.append(f"有 {o['compose']} 人的造句等你看，在看板里。")
    pt = model.get("pets")
    if pt and pt["total"]:
        c = pt["counts"]
        lines.append(f"宠物：{pt['total'] - c[0]}/{pt['total']} 只孵出来了"
                     + "".join(f"，{n} 只{s}" for s, n in zip(pt["stages"][2:], c[2:]) if n)
                     + ("" if pt["first_run"] else
                        f"；比上次放宠物墙新孵出来 {pt['hatched']} 只、长大 {pt['grew']} 只" if pt["hatched"] or pt["grew"] else "")
                     + "。在看板「宠物」页签里。")
    if o["unknown"]:
        lines.append(f"⚠️ 有 {o['unknown']} 条提交的名字不在名单里，看板「每个班谁交了、谁没交」下面能看到是谁。")
    lines.append("每个人的情况系统在盯，想看谁就在看板里搜名字。")
    return "\n".join(lines)


def wrong_words_md(model):
    m = model["meta"]
    out = [f"# 背单词闯关 易错词榜", "",
           f"- 生成时间：{m.get('generated', '')}" + ("（演示数据，不是真学生）" if m.get("demo") else ""),
           "- 口径：每个学生只看第一次提交；「还不会」比「差一点」更该先讲。", ""]
    for u in reversed(model["units"]):
        out += [f"## {u['title']}" + (f"（{u['date']} 发）" if u["date"] else ""), "",
                "| 排名 | 词 / 题 | 中文 | 还不会 | 差一点 | 合计人数 | " + " | ".join(model["classes"]) + " |",
                "|---|---|---|---|---|---|" + "---|" * len(model["classes"])]
        for i, a in enumerate(u["wrong"][:20], 1):
            out.append(f"| {i} | {a['item']} | {a['zh']} | {a['nope']} | {a['shaky']} | {a['people']} | "
                       + " | ".join(str(a["by"].get(c, 0)) for c in model["classes"]) + " |")
        out.append("")
    return "\n".join(out)
