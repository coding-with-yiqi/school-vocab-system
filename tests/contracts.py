#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对一遍「学生页 ↔ 成绩表 ↔ 结果码 ↔ 复习规则」几处各写一份的约定是不是还对得上。不联网、不改文件。

    python3 tests/contracts.py            # 第 3、4 项读 live_check.py 在线上学生页真做一课留下的 tests/_live/学生页.json

对的东西：
1. contract.py 自己：表单映射的列 = 成绩表的列；结果码、数字列都是成绩表里有的列。
2. 学生页模板 assets/student.html（只有这一份）：
   resultCode() 的顺序 = BK2_ORDER，内置 fieldMap = WEB_TO_COLUMN，judge() 只会给出 DETAIL 里的结果。
3. 线上学生页真做一课交出来的 payload() 键 = WEB_TO_COLUMN 的键。
4. shortOf 的标签：线上页面算出来的，和 看板假数据/真表演示/灌成绩.py 的 short_of 一样（演示数据靠它对上「我的复习」）。
5. 明细的结果词：learning.py 和 oral-app 的 logic.ts 都认 pass / near / fail。
"""
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "workbuddy-skill" / "scripts"))
import contract as C  # noqa: E402

bad = []


def check(ok, msg):
    print(("  ✓ " if ok else "  ✗ ") + msg)
    if not ok:
        bad.append(msg)


def js_func(src, name):
    m = re.search(r"function " + name + r"\(\)?[^{]*\{", src)
    if not m:
        return None
    i, depth = m.end(), 1
    while depth:
        depth += {"{": 1, "}": -1}.get(src[i], 0)
        i += 1
    return src[m.start():i]


print("1. contract.py")
check(set(C.WEB_TO_COLUMN.values()) == set(C.SCORE_COLUMNS), "表单映射的列 = 成绩表的列")
check(set(C.BK2_ORDER) <= set(C.SCORE_COLUMNS), "结果码的每一段都是成绩表的列")
check(C.SCORE_NUMS <= set(C.SCORE_COLUMNS), "数字列都在成绩表里")

print("2. 学生页模板")
TPLS = {"assets/student.html": ROOT / "workbuddy-skill" / "assets" / "student.html"}
for tag, p in TPLS.items():
    src = p.read_text(encoding="utf-8")
    rc = js_func(src, "resultCode")
    keys = re.findall(r"p\.(\w+)", rc.split("[", 1)[1]) if rc else []
    check([C.WEB_TO_COLUMN.get(k) for k in keys] == C.BK2_ORDER, f"{tag}：resultCode() 的顺序 = BK2_ORDER")
    m = re.search(r'"fieldMap":(\{[^}]*\})', src)
    check(m and json.loads(m.group(1)) == C.WEB_TO_COLUMN, f"{tag}：模板里内置的 fieldMap = WEB_TO_COLUMN")
    jd = js_func(src, "judge") or ""
    rs = set(re.findall(r'\br:"(\w+)"', jd)) | set(re.findall(r'v\.r="(\w+)"', src))
    check(rs and rs <= set(C.DETAIL), f"{tag}：judge() 只给出 {sorted(C.DETAIL)} 里的结果（实际 {sorted(rs)}）")

live = ROOT / "tests" / "_live" / "学生页.json"
if not live.exists():
    print("3–4. 线上学生页的实际输出：还没有 tests/_live/学生页.json，先跑 python3 tests/live_check.py")
else:
    pg = json.loads(live.read_text(encoding="utf-8"))
    print("3. 线上学生页实际交上来的字段")
    check(set(pg["done"]["payload"]) == set(C.WEB_TO_COLUMN), "payload() 的键 = WEB_TO_COLUMN 的键")
    code = pg["done"]["code"]
    check(code.startswith("BK2|") and len(code.split("|")) == len(C.BK2_ORDER) + 1, f"结果码有 {len(C.BK2_ORDER)} 段")

    print("4. shortOf 标签：线上页面 vs 灌成绩.py")
    src = (ROOT / "看板假数据" / "真表演示" / "灌成绩.py").read_text(encoding="utf-8")
    ns = {}
    exec(src[src.index("def short_of"):src.index("def difficulty")], ns)  # 只取这一个函数，不跑脚本本身（它会读 ~/.beike）
    items = pg["items"]
    diff = [k for k, v in pg["judge"].items() if k in items and ns["short_of"](items[k], k.split("/")[1]) != v.split(" ", 1)[1]]
    seen = sum(1 for k in pg["judge"] if k in items)
    check(seen > 0 and not diff, f"{seen} 道题的标签一样" + (f"；不一样的：{diff[:5]}" if diff else ""))

print("5. 明细的结果词")
lr = (ROOT / "workbuddy-skill" / "scripts" / "learning.py").read_text(encoding="utf-8")
lt = (ROOT / "oral-app" / "server" / "modules" / "review" / "logic.ts").read_text(encoding="utf-8")
for w in ("pass", "near", "fail"):
    check(f'"{w}"' in lr.split("_RES =", 1)[1].split("\n", 1)[0], f"learning.py 认 {w}")
    check(re.search(r"\b" + w + r":", lt.split("const RES", 1)[1].split("\n", 1)[0]) is not None, f"logic.ts 认 {w}")

print()
if bad:
    sys.exit(f"✗ {len(bad)} 处对不上。")
print("✓ 约定全部对得上。")
