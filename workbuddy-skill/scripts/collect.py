#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
结果码 → 成绩表 + 错题池 +「谁没交」

兜底通道：学生交不了飞书表单时，把结果码发到群里，
老师把一整屏消息复制进来，这个脚本自己挑出结果码。

同一个学生同一个包可以交多次（第几次不同），全部保留——
「第一次做对几个」才是真实掌握，最后一次只说明他最终搞定了没有。

用法：
    pbpaste | python3 collect.py -o 成绩.csv --review 错题池.json
    pbpaste | python3 collect.py --roster 高一3班名单.txt      # 顺带算出谁没交
    python3 collect.py 群消息.txt -o 成绩.csv
"""
import argparse, csv, json, re, sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import roster  # noqa: E402  —— 和 publish.py 用同一套读法，两边的人才对得上

from contract import BK2_ORDER as FIELDS  # noqa: E402  字段顺序 = 学生端 resultCode()，见 contract.py


def num(x, d=0):
    try:
        return int(str(x).strip())
    except ValueError:
        return d


def parse(text):
    """同一条（班级,姓名,内容包,第几次）重复粘贴只留最后一份；不同次数全留。"""
    rows = []
    for m in re.finditer(r"BK2\|([^\n\r]*)", text):
        p = [x.strip() for x in m.group(1).split("|")]
        if len(p) < len(FIELDS):
            p += [""] * (len(FIELDS) - len(p))
        row = dict(zip(FIELDS, p[:len(FIELDS)]))
        if not row["姓名"]:
            continue
        key = (row["班级"], row["姓名"], row["内容包"], row["第几次"])
        rows = [r for r in rows
                if (r["班级"], r["姓名"], r["内容包"], r["第几次"]) != key]
        rows.append(row)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", nargs="?", help="群消息文本文件；不给就读 stdin")
    ap.add_argument("-o", "--out", default="成绩.csv")
    ap.add_argument("--review", help="写出错题池 json，供下次 build_pack --review 用")
    ap.add_argument("--roster", action="append", default=[],
                    help="名单文件（和 publish.py 用的是同一份），用来按班算出谁没交")
    ap.add_argument("--pack", help="只看某个内容包")
    a = ap.parse_args()

    text = Path(a.src).read_text(encoding="utf-8") if a.src else sys.stdin.read()
    rows = parse(text)
    if not rows:
        sys.exit("没找到结果码。学生发的那串应该是 BK2| 开头的。\n"
                 "（BK1 是旧版本，重新发布一次网页学生端就会出 BK2。）")
    if a.pack:
        rows = [r for r in rows if a.pack in r["内容包"]]
        if not rows:
            sys.exit(f"没有 {a.pack} 的提交。")

    with open(a.out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    who = {(r["班级"], r["姓名"]) for r in rows}
    print(f"✓ {a.out}　{len(rows)} 条提交，{len(who)} 个人")

    # 多次尝试：第一次才反映真实掌握，最后一次说明最终搞定没有
    tries = defaultdict(list)
    for r in rows:
        tries[(r["班级"], r["姓名"], r["内容包"])].append(r)
    moved = []
    for key, rs in tries.items():
        if len(rs) < 2:
            continue
        rs.sort(key=lambda r: num(r["第几次"]))
        a0, a1 = num(rs[0]["对了"]), num(rs[-1]["对了"])
        moved.append((key[1], a0, a1, len(rs)))
    if moved:                          # 只说人数；逐人的情况在看板「每个人的情况」里
        up = sum(1 for _, a0, a1, _ in moved if a1 > a0)
        print(f"\n  做了不止一次的：{len(moved)} 人，其中 {up} 人最后一次比第一次对得多。")

    # 一个人只看最后一次，不然做了两遍的人会在报告里出现两遍
    latest = {}
    for r in rows:
        k = (r["班级"], r["姓名"], r["内容包"])
        if k not in latest or num(r["第几次"]) >= num(latest[k]["第几次"]):
            latest[k] = r
    last_rows = list(latest.values())

    # 造句每次都要人看，单独一行就够；混进「要你亲自看的」会把每个人都点一遍，等于没点
    compose = [r["姓名"] for r in last_rows if num(r["待老师看"]) > 0]
    if compose:
        print(f"\n  造句要你判的：{len(compose)} 人。")

    need = [r for r in last_rows
            if r["自评"] == "我还不会" or num(r["还不会"]) >= 5 or r["用时偏短"] == "是"]
    if need:
        print(f"  要你亲自看的：{len(need)} 人（自评还不会、错得多、或者用时偏短）。")

    # 谁没交 —— 她每天最花时间的事，而没交的人在提交里根本不存在
    # 按（班级, 姓名）对，不按名字对 —— 3 班和 5 班都有个王小明是常事
    if a.roster:
        rs = roster.read(a.roster)
        done = {(r["班级"], r["姓名"]) for r in rows}
        done_names = {r["姓名"] for r in rows}

        def handed_in(name, cls):
            return (cls, name) in done if cls else name in done_names

        total = sum(len(ns) for ns in rs.values())
        n_done = sum(handed_in(n, c) for c, ns in rs.items() for n in ns)
        head = f"{len(rs)} 个班 " if len(rs) > 1 else ""
        print(f"\n  名单 {head}{total} 人，交了 {n_done} 人。")
        # 谁没交只说人数（项目负责人定：名单只放在看板上）
        parts = []
        for c, ns in rs.items():
            miss = sum(1 for n in ns if not handed_in(n, c))
            parts.append((f"{c} " if len(rs) > 1 else "") + (f"没交 {miss} 人" if miss else "全交了"))
        print("  " + "，".join(parts) + "。")
        if n_done < total:
            print("  名单在看板上，说「看一下成绩」。")
        known = {(c, n) for c, ns in rs.items() for n in ns}
        known_names = {n for ns in rs.values() for n in ns}
        unknown = sorted({f"{c}·{n}" for c, n in done
                          if (c, n) not in known
                          and not ("" in rs and n in known_names)})
        if unknown:
            print(f"  ⚠️ 不在名单里的：{'、'.join(unknown)}　（写错了，或者名单该更新）")

    # 全班易错：「还不会」比「差一点」更该优先，所以记 2 分 / 1 分
    weight, people = Counter(), Counter()
    for r in rows:
        for item in re.split(r"[、,]", r["还不会清单"]):
            if item.strip():
                weight[item.strip()] += 2
                people[item.strip()] += 1
        for item in re.split(r"[、,]", r["差一点清单"]):
            if item.strip():
                weight[item.strip()] += 1
                people[item.strip()] += 1
    if weight:
        print("\n  全班最没拿下的（明天课上先讲这些）：")
        for item, _ in weight.most_common(10):
            print(f"    {people[item]} 人　{item}")
    if a.review:
        pool = [w for w, _ in weight.most_common()
                if re.fullmatch(r"[A-Za-z][A-Za-z ]*", w)]
        Path(a.review).write_text(json.dumps(pool, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        # 有复习计划时，下次发新课按复习计划出题；错题池只是没有计划时的退路，别说成「会排进去」
        print(f"\n✓ {a.review}　记下了 {len(pool)} 个全班错词（没有复习计划时才用它）")


if __name__ == "__main__":
    main()
