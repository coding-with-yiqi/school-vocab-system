# -*- coding: utf-8 -*-
"""学生页「我的复习」现查（方案 A）要的三张表：单元、词表、复习设置。

后端（review-api/）只读飞书，不读这台电脑。它按 learning.py 同一套规则算一个学生没拿下的词，
要知道：每一课的先后（单元表：内容包 / 标题 / 顺序 / 题数 / 发布时间），
每一课的题号对哪个词（词表：内容包 / 词 / 中文 / 来源 / 题号 / 变形）。
「题号」「变形」是给后端新加的两列：题号 = 这个词在这一课里的题（W-003 C-002），
变形 = 填空里出现的样子（devoted），没有明细时从「还不会清单」对回原词用。看板只读前四列，不受影响。

    rows_for(pack, entry)   → (单元行, [词表行…])        一课
    dump(home)              → {"单元": [...], "词表": [...]}   整个课目录（测试、补老课用）
    push_all(lark, pull_rows, base, home)   真发的时候把整个课目录写进飞书（--只生成 不调）

只写普通的课。「我的复习」「期末」那种按人出词的包不写：题号就是 R-词，后端自己对得回来。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import units  # noqa: E402
import learning  # noqa: E402

UNIT_FIELDS = [("内容包", "text"), ("标题", "text"), ("顺序", "number"), ("题数", "number"), ("发布时间", "text")]
WORD_FIELDS = [("内容包", "text"), ("词", "text"), ("中文", "text"), ("来源", "text"),
               ("题号", "text"), ("变形", "text")]
SETTING_FIELDS = [("词", "text"), ("怎么办", "text"), ("中文", "text"), ("改于", "text")]
ONLY_CLOZE = "只在填空"           # 填空考了、闪认没考的词（很少见）：不算这一课的词表，只用来对题号


def rows_for(pk, entry=None):
    entry = entry or {}
    pid = pk["packId"]
    info = learning.PackInfo(pk)
    unit = {"内容包": pid, "标题": entry.get("标题") or pk.get("title", ""),
            "顺序": entry.get("第几课") or 0, "题数": sum(len(l.get("items", [])) for l in pk.get("levels", [])),
            "发布时间": str(entry.get("首发") or entry.get("发布时间") or "")[:10]}
    if info.per_student:
        return unit, []
    rows = {}
    for w in info.vocab:
        rows.setdefault(w, {"内容包": pid, "词": w, "中文": info.zh.get(w, ""), "来源": "本单元",
                            "题号": [], "变形": []})
    for iid, w in info.id_word.items():
        r = rows.setdefault(w, {"内容包": pid, "词": w, "中文": info.zh.get(w, ""), "来源": ONLY_CLOZE,
                                "题号": [], "变形": []})
        r["题号"].append(iid)
    for s, w in info.surface.items():
        if w in rows and s != w.lower():
            rows[w]["变形"].append(s)
    out = []
    for r in rows.values():
        r["题号"] = " ".join(sorted(r["题号"]))
        r["变形"] = " ".join(sorted(set(r["变形"])))
        out.append(r)
    return unit, out


def dump(home=None):
    units_, words = [], []
    packs = units.all_packs(home)
    for e in units.lessons(home, 含撤了=True):
        pk = packs.get(e["packId"])
        if not pk or pk.get("schema") == "beike-words/1":
            continue
        u, ws = rows_for(pk, e)
        units_.append(u)
        words += ws
    return {"单元": units_, "词表": words}


def _ensure_table(lark, base, name, fields, tables):
    """表没有就建；有了就补上缺的列（老 base 的词表没有 题号 / 变形）。返回表 ID。"""
    import json
    if name not in tables:
        d = lark("base", "+table-create", "--base-token", base, "--name", name,
                 "--fields", json.dumps([{"name": n, "type": t} for n, t in fields], ensure_ascii=False))
        tid = (d.get("table") or d).get("id") or (d.get("table") or d).get("table_id")
        if tid:
            return tid
        tables.update({t["name"]: t["id"] for t in lark("base", "+table-list", "--base-token", base)["tables"]})
        return tables[name]
    tid = tables[name]
    d = lark("base", "+field-list", "--base-token", base, "--table-id", tid)
    have = {f.get("field_name") or f.get("name") for f in (d.get("fields") or d.get("items") or [])}
    miss = [{"name": n, "type": t} for n, t in fields if n not in have]
    if miss:
        lark("base", "+field-create", "--base-token", base, "--table-id", tid,
             "--json", json.dumps(miss, ensure_ascii=False))
    return tid


def push_all(lark, pull_rows, base, home=None):
    """真发的时候：课目录里每一课（含撤了的）的单元行、词表行写进飞书。以前的课也补上（老师第一次开现查时，
    之前发的课都还不在表里）。已经有的行按 内容包 / 词 更新，不删行。返回写了几课。"""
    d = dump(home)
    if d["单元"]:
        push(lark, pull_rows, base, d["单元"], d["词表"])
    return len(d["单元"])


def push(lark, pull_rows, base, unit_rows, word_rows):
    """lark / pull_rows 由 beike.py 传进来（同一套 --as user 调用）。"""
    import json
    tables = {t["name"]: t["id"] for t in lark("base", "+table-list", "--base-token", base)["tables"]}
    ut = _ensure_table(lark, base, "单元", UNIT_FIELDS, tables)
    wt = _ensure_table(lark, base, "词表", WORD_FIELDS, tables)

    def upsert(tid, rows, keyf):
        old = {}
        for r in pull_rows(base, tid):
            if keyf(r) and r.get("record_id"):
                old[keyf(r)] = r["record_id"]
        new = [r for r in rows if keyf(r) not in old]
        upd = {old[keyf(r)]: r for r in rows if keyf(r) in old}
        for i in range(0, len(new), 200):
            lark("base", "+record-batch-create", "--base-token", base, "--table-id", tid,
                 "--json", json.dumps({"create_records": new[i:i + 200]}, ensure_ascii=False))
        ids = list(upd)
        for i in range(0, len(ids), 200):
            lark("base", "+record-batch-update", "--base-token", base, "--table-id", tid,
                 "--json", json.dumps({"update_records": {k: upd[k] for k in ids[i:i + 200]}}, ensure_ascii=False))
        return len(new), len(upd)

    s = lambda v: learning._s(v)  # noqa: E731
    upsert(ut, unit_rows, lambda r: s(r.get("内容包")))
    upsert(wt, word_rows, lambda r: (s(r.get("内容包")), s(r.get("词"))))


def push_settings(lark, pull_rows, base, st):
    """老师说「复习 去掉 / 加上」以后：把学期级设置写进飞书「复习设置」表（后端读它）。
    一个词一行，怎么办 = 去掉 / 加上；以前写过、现在不算了的词，怎么办改成空（不删行）。返回现在生效的词数。"""
    import json
    tables = {t["name"]: t["id"] for t in lark("base", "+table-list", "--base-token", base)["tables"]}
    tid = _ensure_table(lark, base, "复习设置", SETTING_FIELDS, tables)
    s = lambda v: learning._s(v)  # noqa: E731
    want = {w.lower(): {"词": w, "怎么办": "去掉", "中文": ""} for w in st.get("去掉", [])}
    want.update({w.lower(): {"词": w, "怎么办": "加上", "中文": st.get("中文", {}).get(w, "")} for w in st.get("加上", [])})
    when = st.get("改于", "")
    old = {}
    for r in pull_rows(base, tid):
        if s(r.get("词")) and r.get("record_id"):
            old[s(r.get("词")).lower()] = (r["record_id"], s(r.get("怎么办")))
    new = [dict(v, 改于=when) for k, v in want.items() if k not in old]
    upd = {rid: dict(want[k], 改于=when) for k, (rid, _) in old.items() if k in want}
    upd.update({rid: {"怎么办": "", "改于": when} for k, (rid, how) in old.items() if k not in want and how})
    if new:
        lark("base", "+record-batch-create", "--base-token", base, "--table-id", tid,
             "--json", json.dumps({"create_records": new}, ensure_ascii=False))
    if upd:
        lark("base", "+record-batch-update", "--base-token", base, "--table-id", tid,
             "--json", json.dumps({"update_records": upd}, ensure_ascii=False))
    return len(want)


if __name__ == "__main__":
    import argparse, json
    ap = argparse.ArgumentParser(description="把课目录导成 单元 / 词表 两张表的行（只打印，不写飞书）")
    ap.add_argument("--home")
    a = ap.parse_args()
    print(json.dumps(dump(a.home), ensure_ascii=False, indent=1))
