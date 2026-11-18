# -*- coding: utf-8 -*-
"""learning.py 和 review-api/rules.mjs 拿同一份数据各算一遍，逐人对：每个词的状态、最后进「我的复习」的词。

    python3 parity.py --home <课目录所在的 home> --records <结果码.txt | 行.json> [--去掉 a,b] [--加上 c] [--不要复习包]

--不要复习包：先把 home 复制一份、删掉 课/review-*（方案 A 以后这台电脑上没有复习包了），看 learning.py 还对不对得上。
--rows：不用 home，直接用这个 JSON 里的 单元 / 词表（演示 base 拉下来的）。Python 那边按这两张表
       拼一个临时课目录（和发课时写进去的一样），词表也当 vocab / 中文 传进去（和 beike「看」一样）。
"""
import argparse, json, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SK = HERE.parents[1] / "workbuddy-skill" / "scripts"
sys.path.insert(0, str(SK))
import learning, review_rows, build_pack, collect  # noqa: E402


def load_records(p):
    t = Path(p).read_text(encoding="utf-8")
    try:
        d = json.loads(t)
        return d.get("records", d) if isinstance(d, dict) else d
    except ValueError:
        return collect.parse(t)


def fake_home(home, rows):
    """单元 / 词表 → 课目录 + 每课的 pack.json（只有 learning 用得到的：题号对哪个词、填空的变形）。"""
    S = learning._s
    lessons, packs = [], {}
    for u in rows["单元"]:
        pid = S(u["内容包"])
        lessons.append({"packId": pid, "标题": S(u.get("标题")), "第几课": learning._num(u.get("顺序")) or None,
                        "首发": S(u.get("发布时间"))[:10]})
        packs[pid] = {"packId": pid, "items": {}}
    for w in rows["词表"]:
        pid, en = S(w["内容包"]), S(w["词"])
        pk = packs.setdefault(pid, {"packId": pid, "items": {}})
        forms = S(w.get("变形")).split()
        for iid in S(w.get("题号")).split():
            if iid.startswith("C-"):
                pk["items"][iid] = {"type": "cloze", "word": en, "answer": forms[0] if forms else en}
            else:
                pk["items"][iid] = {"type": "word", "en": en, "zh": S(w.get("中文"))}
    (home / "课").mkdir(parents=True)
    (home / "课" / "目录.json").write_text(json.dumps({"课": lessons, "复习": None}, ensure_ascii=False), encoding="utf-8")
    for pid, pk in packs.items():
        if pk["items"]:
            (home / "课" / pid).mkdir()
            (home / "课" / pid / "pack.json").write_text(json.dumps(pk, ensure_ascii=False), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--home")
    ap.add_argument("--records", required=True)
    ap.add_argument("--rows")
    ap.add_argument("--去掉", dest="drop", default="")
    ap.add_argument("--加上", dest="add", default="")
    ap.add_argument("--不要复习包", dest="noreview", action="store_true")
    a = ap.parse_args()
    drop = [w for w in a.drop.split(",") if w]
    add = [w for w in a.add.split(",") if w]
    recs = load_records(a.records)
    tmp = Path(tempfile.mkdtemp(prefix="parity-"))
    try:
        home = tmp / "home"
        vocab, zh = {}, {}
        if a.home:
            shutil.copytree(a.home, home)
        else:
            rows = json.loads(Path(a.rows).read_text(encoding="utf-8"))
            fake_home(home, rows)
            for w in rows["词表"]:
                vocab.setdefault(learning._s(w["内容包"]), []).append(learning._s(w["词"]))
                zh.setdefault(learning._s(w["词"]), learning._s(w.get("中文")))
        (home / "复习计划.json").unlink(missing_ok=True)
        if a.noreview:
            for d in (home / "课").glob("review-*"):
                shutil.rmtree(d)
        rows = json.loads(Path(a.rows).read_text(encoding="utf-8")) if a.rows else review_rows.dump(home)
        # ── Python：和 beike.draft_review 一样的算法，计划写在临时 home 里
        known = build_pack.load_known(home / "发布", home / "课")
        zh.update({en: z for en, z in known.values() if z and not zh.get(en)})
        model = learning.compute(recs, home=home, vocab=vocab, zh=zh)
        (home / "复习设置.json").unlink(missing_ok=True)
        learning.save_settings({"去掉": drop, "加上": add, "中文": {}, "下次关掉": False}, home)
        learning.draft_plan(model, "对照", home)
        plan = learning.load_plan(home)
        py_list = {k: [w for w in ws if w in plan["中文"]] for k, ws in plan["每人"].items()}
        # ── JS
        f = tmp / "in.json"
        f.write_text(json.dumps({"records": recs, "units": rows["单元"], "words": rows["词表"],
                                 "drop": drop, "add": add}, ensure_ascii=False), encoding="utf-8")
        js = json.loads(subprocess.run(["node", str(HERE / "js_side.mjs"), str(f)],
                                       capture_output=True, text=True, check=True).stdout)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    bad = []
    keys = sorted(set(model["学生"]) | set(js))
    for k in keys:
        ps = model["学生"].get(k, {})
        jsk = js.get(k, {"state": {}, "list": []})
        if ps != jsk["state"]:
            diff = {w: (ps.get(w), jsk["state"].get(w)) for w in set(ps) | set(jsk["state"])
                    if ps.get(w) != jsk["state"].get(w)}
            bad.append((k, "状态", dict(list(diff.items())[:3])))
        jl = [x["en"] for x in jsk["list"]]
        if py_list.get(k, []) != jl:
            bad.append((k, "复习单", (py_list.get(k, []), jl)))
    n_list = sum(1 for k in keys if py_list.get(k))
    words = sum(len(v) for v in py_list.values())
    print(f"{len(keys)} 个学生，{n_list} 人有复习单，一共 {words} 个词；去掉 {drop or '无'}，加上 {add or '无'}")
    if bad:
        print(f"✗ 对不上 {len(bad)} 处：")
        for b in bad[:10]:
            print("   ", json.dumps(b, ensure_ascii=False)[:400])
        sys.exit(1)
    print("✓ 两边逐人一样（每个词的状态 + 复习单的词和顺序）")


if __name__ == "__main__":
    main()
