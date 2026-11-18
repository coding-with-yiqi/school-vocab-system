#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把假学生的成绩按「真课包」写进真成绩表（演示用）。全是假名，不对应任何真学生。

前提：~/.beike/名单.txt 已经是 make_fake.py 那 129 个假学生；
      ~/.beike/课/ 里已经用真「发」发过这几课（题号、标签都从真课包里读，「我的复习」才对得上）。

    python3 灌成绩.py            # 只生成 成绩_预览.json，不写飞书
    python3 灌成绩.py --写入      # 写进 config.json 里那张成绩表（表必须是空的）

和学生页（assets/student.html）保持一致：
- 明细 = 题号:pass/near/fail/review，按关卡顺序
- 还不会清单 / 差一点清单 = shortOf(题号) 的标签，用「、」连
"""
import argparse, json, random, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent.parent / "workbuddy-skill" / "scripts"))
import make_fake as mf   # noqa: E402  只借它的名单（同一个随机种子，和 名单.txt 一样）
import beike             # noqa: E402

rng = random.Random(20261119)
HARD = [  # 每课最难的几个词（越大越难），其余词默认 .25
    {"acknowledge": .9, "abandon": .6, "physician": .7, "devote": .5, "malaria": .4},
    {"privacy": .5, "efficient": .7, "artificial": .6, "recognize": .3, "convenient": .4},
    {"boundary": .6, "glacier": .7, "attraction": .4, "preserve": .5},
]
SUBMIT_RATE = [0.96, 0.93, 0.62]       # 第 3 课刚发，很多人还没做
COMPOSE = [
    ["She devoted her whole life to science and never abandoned her dream.",
     "He devoted three years to the project, but he didn't abandon it.",
     "Never abandon your goal if you devote yourself to it."],
    ["The app can forecast the weather, but it also knows too much about my privacy.",
     "Robots can forecast the future, but we must protect our privacy.",
     "I want a phone that can forecast rain and keep my privacy safe."],
    ["The boundary of the park is marked by trees, and the landscape is beautiful.",
     "We stopped at the boundary and took photos of the landscape.",
     "The landscape near the boundary is the most beautiful in the park."],
]
CODE = {"对了": "pass", "差一点": "near", "还不会": "fail", "待老师看": "review"}


def short_of(it, iid):
    t = it.get("type")
    if t == "word":
        return it.get("en") or iid
    if t == "cloze":
        return it.get("answer") or iid
    if t == "compose":
        return "造句 " + "+".join(it.get("must") or [])
    if t == "fix":
        return "改错 " + (it.get("reason") or "") + "·" + " ".join(str(it.get("answer") or "").split(" ")[:3])
    if t == "sentence":
        return "默写 " + str(it.get("zh") or "").removeprefix("请默写：")[:10]
    return iid


def difficulty(it, hard):
    t = it.get("type")
    if t == "word":
        return hard.get(it.get("en", ""), .25)
    if t == "cloze":
        ans = str(it.get("answer", ""))
        return max([d for w, d in hard.items() if ans.startswith(w[:5])] or [.25]) * .8
    return {"fix": .45, "sentence": .5}.get(t, 0)


def outcome(skill, diff, fast):
    if fast:
        return rng.choices(["对了", "差一点", "还不会"], [.3, .2, .5])[0]
    p = skill + .16 - diff * .4
    r = rng.random()
    return "对了" if r < p else ("差一点" if r < p + .18 else "还不会")


def lessons(home):
    cat = json.loads((home / "课" / "目录.json").read_text(encoding="utf-8"))
    out = []
    for e in cat["课"]:
        if e.get("撤了") or e.get("试做") or e.get("类型") != "课":
            continue
        pk = json.loads((home / "课" / e["packId"] / "pack.json").read_text(encoding="utf-8"))
        order = [i for lv in pk["levels"] for i in lv["items"]]
        out.append((e["packId"], pk["items"], order))
    return out


def build(home):
    students = mf.names()
    roster = beike.roster.read(home / "名单.txt")
    want = {(c, n) for c, ns in roster.items() for n in ns}
    got = {(s["班级"], s["姓名"]) for s in students}
    if want != got:
        sys.exit("~/.beike/名单.txt 不是 make_fake 那 129 个假学生，不灌。")
    skill = {k: min(.98, max(.25, rng.gauss(.78, .14))) for k in sorted(got)}
    never = set(rng.sample(sorted(k for k in skill if k[0] == "高一5班"), 2))   # 一次都没交
    lazy = set(rng.sample(sorted(skill), 6))                                     # 常常做太快
    records = []
    for ui, (pid, items, order) in enumerate(lessons(home)):
        hard = HARD[ui] if ui < len(HARD) else {}
        for s in students:
            k = (s["班级"], s["姓名"])
            if k in never or rng.random() > SUBMIT_RATE[min(ui, len(SUBMIT_RATE) - 1)]:
                continue
            tries = 1 + (rng.random() < .12) + (rng.random() < .04)
            for t in range(1, tries + 1):
                fast = (k in lazy and rng.random() < .55 and t == 1) or rng.random() < .015
                res = {}
                for iid in order:
                    it = items[iid]
                    res[iid] = "待老师看" if it["type"] == "compose" else \
                        outcome(skill[k] + .12 * (t - 1), difficulty(it, hard), fast)
                cnt = {x: sum(1 for r in res.values() if r == x) for x in CODE}
                nope = list(dict.fromkeys(short_of(items[i], i) for i, r in res.items() if r == "还不会"))
                shaky = list(dict.fromkeys(short_of(items[i], i) for i, r in res.items() if r == "差一点"))
                secs = rng.randint(55, 110) if fast else max(180, int(rng.gauss(560, 150) - 60 * (t - 1)))
                selfr = ("会了" if fast or cnt["还不会"] < 3 else rng.choice(["还有点不稳", "我还不会", "会了"])) \
                    if rng.random() > .1 else "没选"
                records.append({
                    "班级": s["班级"], "姓名": s["姓名"], "内容包": pid, "第几次": t,
                    "对了": cnt["对了"], "差一点": cnt["差一点"], "还不会": cnt["还不会"], "待老师看": cnt["待老师看"],
                    "还不会清单": "、".join(nope), "差一点清单": "、".join(shaky),
                    "造句原文": "ok ok ok ok ok ok ok ok" if fast else rng.choice(COMPOSE[ui % len(COMPOSE)]),
                    "自评": selfr, "用时秒": secs, "用时偏短": "是" if fast else "",
                    "明细": ",".join(f"{i}:{CODE[r]}" for i, r in res.items())})
        if ui == 1:      # 一条名字打错的提交（名单里是别的写法）
            r = dict(records[-1]); r.update(班级="高一4班", 姓名="张嘉仪", 第几次=1)
            records.append(r)
    return records


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--写入", dest="write", action="store_true")
    a = ap.parse_args()
    recs = build(beike.HOME)
    (HERE / "成绩_预览.json").write_text(json.dumps(recs, ensure_ascii=False, indent=1), encoding="utf-8")
    by = {}
    for r in recs:
        by[r["内容包"]] = by.get(r["内容包"], 0) + 1
    print(f"生成 {len(recs)} 条：", by)
    if a.write:
        c = beike.cfg()
        base, table = c["base"], c["table"]
        if beike.pull_rows(base, table):
            sys.exit("成绩表里已经有记录了，不灌（只往空表里灌，免得和真提交混在一起）。")
        rows = [{k: v for k, v in r.items() if v != ""} for r in recs]
        for i in range(0, len(rows), 200):
            beike.lark("base", "+record-batch-create", "--base-token", base, "--table-id", table,
                       "--json", json.dumps({"create_records": rows[i:i + 200]}, ensure_ascii=False))
        print(f"写进飞书了：{len(rows)} 条。")
