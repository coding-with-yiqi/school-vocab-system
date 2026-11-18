#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成一套逼真的假数据，给看板演示和测试用。全是假名，不对应任何真学生。

    python3 make_fake.py                 # 写出 fake.json（本地，看板可以直接读）
    python3 make_fake.py --push          # 另外在飞书里新建一个「背单词闯关·假数据演示」base，四张表都写进去

故意放进去的情况：
- 有人没交：5 班两个人一次都没交；第 3 单元刚发，很多人还没做。
- 有人做太快：每个单元几个人用时不到 2 分钟，乱点。
- 有人反复做：约一成的人做了 2–3 次，越做越好。
- 错词复习回来：第 2、3 单元开头各排了几个上个单元全班没拿下的词，多数人这次对了。
- 一条名字打错的提交（不在名单里）。
- 两个班都有「王小明」，看板要按 班级+姓名 对，不能串。
"""
import argparse, json, random, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
rng = random.Random(20261118)

CLASSES = [("高一3班", 43), ("高一4班", 42), ("高一5班", 44)]
SUR = list("王李张刘陈杨赵黄周吴徐孙胡朱高林何郭马罗梁宋郑谢韩唐冯于董萧程曹袁邓许傅沈曾彭吕苏卢蒋蔡贾丁魏薛叶阎余潘杜戴夏钟汪田任姜范方石姚谭廖邹熊金陆郝孔白崔康毛邱秦江史顾侯邵孟龙万段雷钱汤尹黎易常武乔贺赖龚文")
GIVEN = ["子涵", "雨桐", "梓萱", "一诺", "欣怡", "浩然", "宇轩", "思远", "嘉怡", "沐", "星遥", "听雨",
         "俊杰", "博文", "晨曦", "语嫣", "皓轩", "若溪", "佳琪", "明轩", "梦琪", "天佑", "安然", "书瑶",
         "子墨", "一鸣", "可欣", "铭泽", "诗涵", "奕辰", "雅琳", "睿", "清扬", "芷若", "泽宇", "静怡",
         "嘉树", "思彤", "景行", "知夏", "以沫", "承泽", "欣然", "昊天", "梓轩", "悦", "致远", "婉清"]

# 三个单元。词是人教版选择性必修一的样例，只用于演示。
UNITS = [
    {"内容包": "RJ-XB1-U1-20261020", "标题": "Unit 1 People of Achievement", "发布时间": "2026-10-20",
     "new": [("achievement", "成就"), ("devote", "致力于"), ("physician", "内科医生"), ("malaria", "疟疾"),
             ("extract", "提取"), ("insist", "坚持"), ("acknowledge", "承认；致谢"), ("abandon", "放弃")],
     "hard": {"acknowledge": .9, "abandon": .6, "physician": .7, "devote": .5, "malaria": .4}},
    {"内容包": "RJ-XB1-U2-20261103", "标题": "Unit 2 Looking into the Future", "发布时间": "2026-11-03",
     "new": [("forecast", "预报"), ("privacy", "隐私"), ("recognize", "认出"), ("efficient", "效率高的"),
             ("artificial", "人造的")],
     "hard": {"privacy": .5, "efficient": .7, "artificial": .6, "recognize": .3}},
    {"内容包": "RJ-XB1-U3-20261117", "标题": "Unit 3 Fascinating Parks", "发布时间": "2026-11-17",
     "new": [("boundary", "边界"), ("landscape", "风景"), ("attraction", "景点"), ("wildlife", "野生动物"),
             ("glacier", "冰川")],
     "hard": {"boundary": .6, "glacier": .7, "attraction": .4}},
]
SUBMIT_RATE = [0.96, 0.93, 0.62]       # 第 3 单元昨天才发
FIX = [("时态", "He devoted his"), ("搭配", "She has devoted"), ("词性", "Her achievement was"), ("拼写", "The physician insisted")]
RECALL = ["他把一生都奉献给", "她的成就得到了全", "在失败了很多次之"]


def names():
    out, used_any = [], set()
    for cls, n in CLASSES:
        seen = set()
        while len(seen) < n:
            nm = rng.choice(SUR) + rng.choice(GIVEN)
            if nm in seen:
                continue
            seen.add(nm)
        lst = sorted(seen)
        if cls in ("高一3班", "高一5班"):
            lst[rng.randrange(len(lst))] = "王小明"     # 两个班都有王小明
        out += [{"班级": cls, "姓名": nm} for nm in lst]
    return out


def unit_items(ui, review):
    """返回 [(id, label, kind, 难度)] 和这个单元的词表行。review = 上单元全班最没拿下的 3 个词。"""
    u = UNITS[ui]
    words = [(w, zh, "复习·" + src) for w, zh, src in review] + [(w, zh, "本单元") for w, zh in u["new"]]
    words = words[:8]
    hard = dict(u["hard"])
    items = []
    for i, (w, _, src) in enumerate(words):
        items.append((f"W-{i+1:03d}", w, "word", hard.get(w, .25 if src == "本单元" else .55)))
    for i, (w, _, _) in enumerate(words[-4:]):
        items.append((f"C-{i+1:03d}", w, "cloze", hard.get(w, .25) * .8))
    items.append(("P-001", "造句 " + "+".join(x[0] for x in words[:2]), "compose", 0))
    for i, (why, head) in enumerate(FIX[: 4 - (ui > 0)]):
        items.append((f"E-{i+1:03d}", f"改错 {why}·{head}", "fix", .45))
    for i, s in enumerate(RECALL):
        items.append((f"S-{i+1:03d}", "默写 " + s, "sentence", .5))
    vocab = [{"内容包": u["内容包"], "词": w, "中文": zh, "来源": src} for w, zh, src in words]
    return items, vocab


def outcome(skill, diff, fast, prior_wrong=False):
    if fast:
        return rng.choices(["对了", "差一点", "还不会"], [.3, .2, .5])[0]
    p = skill + .16 - diff * .4 + (0.25 if prior_wrong else 0)   # 上次错过、这次复习：老师讲过了，更容易对
    r = rng.random()
    if r < p:
        return "对了"
    return "差一点" if r < p + .18 else "还不会"


def build():
    students = names()
    skill = {(s["班级"], s["姓名"]): min(.98, max(.25, rng.gauss(.78, .14))) for s in students}
    never = set(rng.sample([k for k in skill if k[0] == "高一5班"], 2))      # 一次都没交的两个人
    lazy = set(rng.sample(list(skill), 6))                                    # 经常做太快的人
    units, vocab, records = [], [], []
    review = []
    wrong_by_student = {}            # (班级,姓名) -> 上个单元错过的词
    for ui, u in enumerate(UNITS):
        items, v = unit_items(ui, review)
        vocab += v
        n_items = len(items)
        units.append({"内容包": u["内容包"], "标题": u["标题"], "顺序": ui + 1,
                      "题数": n_items, "发布时间": u["发布时间"]})
        word_people = {}
        new_wrong = {}
        for s in students:
            k = (s["班级"], s["姓名"])
            if k in never or rng.random() > SUBMIT_RATE[ui]:
                continue
            tries = 1 + (rng.random() < .12) + (rng.random() < .04)
            sk = skill[k]
            for t in range(1, tries + 1):
                fast = (k in lazy and rng.random() < .55 and t == 1) or rng.random() < .015
                res = {}
                for iid, label, kind, diff in items:
                    if kind == "compose":
                        res[iid] = "待老师看"
                        continue
                    res[iid] = outcome(sk + .12 * (t - 1), diff, fast,
                                       label in wrong_by_student.get(k, ()))
                cnt = {x: sum(1 for r in res.values() if r == x) for x in ("对了", "差一点", "还不会", "待老师看")}
                lab = {iid: label for iid, label, _, _ in items}
                nope = list(dict.fromkeys(lab[i] for i, r in res.items() if r == "还不会"))
                shaky = list(dict.fromkeys(lab[i] for i, r in res.items() if r == "差一点" and lab[i] not in nope))
                secs = rng.randint(55, 110) if fast else int(rng.gauss(560, 150) - 60 * (t - 1))
                selfr = ("会了" if fast or cnt["还不会"] < 3 else rng.choice(["还有点不稳", "我还不会", "会了"])) \
                    if rng.random() > .1 else "没选"
                rec = {"班级": s["班级"], "姓名": s["姓名"], "内容包": u["内容包"], "第几次": t,
                       "对了": cnt["对了"], "差一点": cnt["差一点"], "还不会": cnt["还不会"],
                       "待老师看": cnt["待老师看"], "还不会清单": "、".join(nope), "差一点清单": "、".join(shaky),
                       "造句原文": "She devoted her life to it." if not fast else "ok ok ok ok ok ok ok ok",
                       "自评": selfr, "用时秒": max(secs, 50), "用时偏短": "是" if fast else "",
                       "明细": ",".join(f"{i}:{ {'对了': 'ok', '差一点': 'near', '还不会': 'no', '待老师看': 'review'}[r]}"
                                        for i, r in res.items())}
                records.append(rec)
                if t == 1:
                    wl = [w for w in nope + shaky if " " not in w]
                    new_wrong[k] = set(wl)
                    for w in wl:
                        word_people[w] = word_people.get(w, 0) + (2 if w in nope else 1)
        # 一条名字打错的
        if ui == 1:
            r = dict(records[-1]); r.update(班级="高一4班", 姓名="张嘉仪", 第几次=1)
            records.append(r)
        top = sorted(word_people.items(), key=lambda x: -x[1])[:3]
        zh = {w: z for w, z in u["new"]} | {x[0]: x[1] for x in review}
        review = [(w, zh.get(w, ""), f"Unit {ui+1}") for w, _ in top]
        wrong_by_student = new_wrong
    return {"students": students, "units": units, "words": vocab, "records": records}


# ── 写进飞书 ─────────────────────────────────────────
def lark_mod():
    sys.path.insert(0, str(HERE.parent / "workbuddy-skill" / "scripts"))
    import beike
    return beike


def refill(base, data):
    """已经建过假数据 base：清空四张表再重写（只用于本脚本自己建的那个演示 base）。"""
    beike = lark_mod()
    info = beike.lark("base", "+base-get", "--base-token", base)
    if "假数据" not in json.dumps(info, ensure_ascii=False):
        sys.exit("这不是假数据演示 base，不动。")
    for t in ("成绩", "名单", "单元", "词表"):
        ids = [r["record_id"] for r in beike.pull_rows(base, t)]
        for i in range(0, len(ids), 200):
            beike.lark("base", "+record-delete", "--base-token", base, "--table-id", t, "--yes",
                       "--json", json.dumps({"record_id_list": ids[i:i + 200]}))
    for t, rows in (("名单", data["students"]), ("单元", data["units"]), ("词表", data["words"]),
                    ("成绩", [{k: v for k, v in r.items() if v != ""} for r in data["records"]])):
        for i in range(0, len(rows), 200):
            beike.lark("base", "+record-batch-create", "--base-token", base, "--table-id", t,
                       "--json", json.dumps({"create_records": rows[i:i + 200]}, ensure_ascii=False))
    print("假数据 base 重写好了。")


def push(data):
    beike = lark_mod()
    F = beike.FIELDS
    fields = [{"name": n, "type": "number" if n in beike.NUMS else "text"} for n in F]
    d = beike.lark("base", "+base-create", "--name", "背单词闯关·假数据演示", "--time-zone", "Asia/Shanghai",
                   "--table-name", "成绩", "--fields", json.dumps(fields, ensure_ascii=False))
    base, url = d["base"]["base_token"], d["base"]["url"]
    tables = {"名单": [("班级", "text"), ("姓名", "text")],
              "单元": [("内容包", "text"), ("标题", "text"), ("顺序", "number"), ("题数", "number"), ("发布时间", "text")],
              "词表": [("内容包", "text"), ("词", "text"), ("中文", "text"), ("来源", "text")]}
    for name, fs in tables.items():
        beike.lark("base", "+table-create", "--base-token", base, "--name", name, "--fields",
                   json.dumps([{"name": n, "type": t} for n, t in fs], ensure_ascii=False))
    ids = {t["name"]: t["id"] for t in beike.lark("base", "+table-list", "--base-token", base)["tables"]}

    def put(table, rows):
        for i in range(0, len(rows), 200):
            beike.lark("base", "+record-batch-create", "--base-token", base, "--table-id", ids[table],
                       "--json", json.dumps({"create_records": rows[i:i + 200]}, ensure_ascii=False))
    put("名单", data["students"])
    put("单元", data["units"])
    put("词表", data["words"])
    put("成绩", [{k: v for k, v in r.items() if v != ""} for r in data["records"]])
    print(f"假数据 base 建好了：{url}")
    print(f"base_token={base}")
    return base, url


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--refill", metavar="BASE_TOKEN", help="清空已有的假数据 base 再重写")
    a = ap.parse_args()
    data = build()
    (HERE / "fake.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"fake.json：{len(data['students'])} 人，{len(data['units'])} 个单元，{len(data['records'])} 条提交")
    if a.push:
        push(data)
    elif a.refill:
        refill(a.refill, data)
