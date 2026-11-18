# -*- coding: utf-8 -*-
"""本地后端（server.mjs，读演示 base）返回的单子 == learning.py 用同一份数据算出来的单子；再试限流。
    python3 e2e.py <rows.json> <records.json> [端口]"""
import json, sys, subprocess, tempfile, urllib.parse, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
rows, recs = sys.argv[1], sys.argv[2]
port = sys.argv[3] if len(sys.argv) > 3 else "8787"
import parity, learning, shutil  # noqa: E402

tmp = Path(tempfile.mkdtemp())
home = tmp / "h"
R = json.loads(Path(rows).read_text(encoding="utf-8"))
parity.fake_home(home, R)
records = json.loads(Path(recs).read_text(encoding="utf-8"))
vocab, zh = {}, {}
for w in R["词表"]:
    vocab.setdefault(learning._s(w["内容包"]), []).append(learning._s(w["词"]))
    zh.setdefault(learning._s(w["词"]), learning._s(w.get("中文")))
m = learning.compute(records, home=home, vocab=vocab, zh=zh)
learning.draft_plan(m, "e2e", home)
plan = learning.load_plan(home)
shutil.rmtree(tmp)


def ask(cls, name, ip=None):
    q = urllib.parse.urlencode({"班级": cls, "姓名": name})
    req = urllib.request.Request(f"http://localhost:{port}/api/review?{q}")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


keys = sorted(m["学生"])
ok = bad = 0
for k in keys[:18]:
    cls, name = k.split("·", 1)
    st, body = ask(cls, name)
    want = [w for w in plan["每人"].get(k, []) if w in plan["中文"]]
    got = [x["en"] for x in body.get("words", [])]
    if st == 200 and got == want and all(set(x) == {"en", "zh", "accept", "hint"} for x in body["words"]):
        ok += 1
    else:
        bad += 1
        print("✗", k, st, want, got)
print(f"后端 vs learning.py：{ok} 人一样，{bad} 人不一样")
st, body = ask("高一3班", "没有这个人")
print("名单外的名字：", st, body)
codes = []
for k in keys[18:30]:
    cls, name = k.split("·", 1)
    codes.append(ask(cls, name)[0])
print("同一个 IP 接着查第 19~30 个人：", codes)
st, body = ask(*keys[0].split("·", 1))
print("再查第 1 个人（已经查过的）：", st)
