#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""线上验证：用老师电脑上真的配置、真的飞书、真的学生页跑一遍，只读不写。

    python3 tests/live_check.py                         # 四步全跑
    python3 tests/live_check.py --对比 <旧 scripts 目录>  # 再拿旧版代码跑同一组命令，逐字比（时间戳抹掉）
    python3 tests/live_check.py --复习人数 5             # 「我的复习」查几个人（接口限流：同一 IP 一小时 20 人）

1. 老师命令：把 ~/.beike（或 $BEIKE_HOME）拷一份，beike.py 指到拷贝，lark-cli 换成 readonly_lark.py：
   读飞书照常读线上，写飞书一律拦下。跑 状态 / 课 / 复习 / 看 / 收 / 收尾 / 期末 / 宠物 / 发 --只生成 和演示模式，
   每条都要正常退出，而且一条写调用都没发生（收用的是表里已有的结果码，本来就不该写）。
2. 线上学生页：GET 学生链接，页面里的 judge / shortOf / resultCode / payload / save 要和 assets/student.html 一字不差，
   内置的 fieldMap 要等于 contract.WEB_TO_COLUMN。
3. 线上「我的复习」：挑几个人 GET 复习接口，回来的词要和第 1 步里 learning.py 用真成绩表算的复习单一样。
4. 浏览器真做一课（Playwright）：结果码和表单预填落到成绩表应该是同一行。不点提交。
最后跑 contracts.py。产出都在 tests/_live/（已 gitignore，里面有真名单和真成绩，别外传）。
"""
import argparse, json, os, re, shutil, subprocess, sys, urllib.parse, urllib.request
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SK = ROOT / "workbuddy-skill" / "scripts"
OUT = HERE / "_live"
sys.path.insert(0, str(SK))
import contract, collect, lark_cli  # noqa: E402

SRC_HOME = Path(os.path.expanduser(os.environ.get("BEIKE_HOME", "~/.beike")))
U1 = ROOT / "workbuddy-skill" / "示例词表_Unit1.md"
EP = ROOT / "workbuddy-skill" / "示例剧情_一株青蒿.json"
CMDS = [("状态", ["状态"]), ("课", ["课"]), ("复习", ["复习"]),
        ("看", ["看", "--不打开", "--不开店"]), ("看_摘要", ["看", "--摘要"]),
        ("收_表里已有", ["收", "<CODES>", "--不抓微信"]),
        ("收尾", ["收尾"]), ("期末_只生成", ["期末", "--只生成"]), ("宠物", ["宠物", "--不打开"]),
        ("发_只生成", ["发", str(U1), "--剧情", str(EP), "--只生成"]),
        ("看_演示", ["看", "--演示", "--不打开", "--不开店"]), ("收尾_演示", ["收尾", "--演示"]),
        ("期末_演示", ["期末", "--演示", "--只生成"]), ("宠物_演示", ["宠物", "--演示", "--不打开"])]
CODES_PY = r'''
import sys; sys.path.insert(0, sys.argv[1])
import beike
c = beike.cfg()
open(sys.argv[2], "w", encoding="utf-8").write("\n".join(beike.table_codes(c["base"], c["table"])) + "\n")
'''
PW = os.environ.get("PLAYWRIGHT_DIR") or next(
    (str(p) for p in [Path.home() / ".agents/skills/gstack/node_modules/playwright"] if p.exists()), "playwright")
bad = []


def check(ok, msg):
    print(("  ✓ " if ok else "  ✗ ") + msg)
    if not ok:
        bad.append(msg)


def teacher_cmds(tag, scripts, real_cli):
    """拷一份 home，用 scripts 目录下的 beike.py 跑 CMDS；飞书只读。返回 (屏幕输出目录, home 拷贝)。"""
    home, scr, log = OUT / f"home_{tag}", OUT / f"屏幕_{tag}", OUT / f"飞书调用_{tag}.ndjson"
    for p in (home, scr):
        shutil.rmtree(p, ignore_errors=True)
    shutil.copytree(SRC_HOME, home)
    scr.mkdir(parents=True)
    log.unlink(missing_ok=True)
    env = dict(os.environ, BEIKE_HOME=str(home), LARK_CLI=str(HERE / "readonly_lark.py"), REAL_LARK_CLI=real_cli,
               READONLY_LOG=str(log), PYTHONDONTWRITEBYTECODE="1")
    codes = OUT / f"表里已有的结果码_{tag}.txt"
    subprocess.run([sys.executable, "-c", CODES_PY, str(scripts), str(codes)], env=env, check=True)
    has_demo = bool(json.loads((home / "config.json").read_text(encoding="utf-8")).get("demo_base"))
    for i, (name, args) in enumerate(CMDS, 1):
        if "--演示" in args and not has_demo:
            print(f"  - {tag}：beike.py {' '.join(args)}　跳过（config 里没配 demo_base，演示模式本来就用不了）")
            continue
        args = [str(codes) if a == "<CODES>" else a for a in args]
        p = subprocess.run([sys.executable, str(scripts / "beike.py"), *args], capture_output=True, text=True,
                           env=env, cwd=str(scripts), timeout=600)
        (scr / f"{i:02d}_{name}.txt").write_text(
            f"exit={p.returncode}\n{p.stdout}\n--stderr--\n{p.stderr}".replace(str(home), "<HOME>"), encoding="utf-8")
        check(p.returncode == 0, f"{tag}：beike.py {' '.join(a for a in args if not a.startswith('/'))}")
    calls = Counter(next(iter(json.loads(x))) for x in log.read_text(encoding="utf-8").splitlines()) if log.exists() else {}
    check(not calls.get("拦下"), f"{tag}：读线上飞书 {calls.get('放行', 0)} 次，想写 {calls.get('拦下', 0)} 次（应为 0）")
    return scr, home


_T = [(re.compile(rb"20\d\d-\d\d-\d\d[ T]\d\d:\d\d(:\d\d)?"), b"<T>"), (re.compile(rb"\d{8}-\d{4}"), b"<T>"),
      (re.compile(rb"\d{4}-\d{4,6}"), b"<T>"), (re.compile(rb"\b\d\d:\d\d\b"), b"<T>")]


def same_tree(a, b, ha, hb):
    """两个目录逐个文件比，抹掉时间戳和各自的 home 路径。返回 (一样的个数, 不一样的列表)。"""
    def n(x, home):
        x = x.replace(str(home).encode(), b"<HOME>")
        for r, s in _T:
            x = r.sub(s, x)
        return x

    def files(root):
        d = {}
        for p in sorted(root.rglob("*")):
            if p.is_file():
                d.setdefault(n(str(p.relative_to(root)).encode(), root).decode(), []).append(p)
        return d
    fa, fb, same, diff = files(a), files(b), 0, []
    for k in sorted(set(fa) | set(fb)):
        if len(fa.get(k, [])) != len(fb.get(k, [])):
            diff.append(k)
            continue
        for x, y in zip(fa[k], fb[k]):
            if n(x.read_bytes(), ha) == n(y.read_bytes(), hb):
                same += 1
            else:
                diff.append(k)
    return same, diff


def js_func(src, name):
    m = re.search(r"function " + name + r"\(\)?[^{]*\{", src)
    if not m:
        return None
    i, depth = m.end(), 1
    while depth:
        depth += {"{": 1, "}": -1}.get(src[i], 0)
        i += 1
    return src[m.start():i]


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (live_check)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, r.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--对比", dest="old", help="旧版 workbuddy-skill/scripts 目录：同一组命令再跑一遍，逐字比")
    ap.add_argument("--复习人数", dest="n", type=int, default=5)
    a = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    cfg = json.loads((SRC_HOME / "config.json").read_text(encoding="utf-8"))
    os.environ.pop("LARK_CLI", None) if os.environ.get("LARK_CLI", "").endswith("readonly_lark.py") else None
    real_cli = lark_cli.find_cli()

    print("1. 老师命令（线上飞书只读）")
    scr, home = teacher_cmds("现在", SK, real_cli)
    if a.old:
        scr0, home0 = teacher_cmds("旧版", Path(a.old).resolve(), real_cli)
        s1, d1 = same_tree(scr0, scr, home0, home)
        s2, d2 = same_tree(home0, home, home0, home)
        check(not d1 and not d2, f"旧版 vs 现在：比了 {s1 + s2 + len(d1) + len(d2)} 个文件，不一样 {len(d1) + len(d2)} 个"
              + (f"：{(d1 + d2)[:8]}" if d1 or d2 else ""))

    print("2. 线上学生页")
    st, raw = get(cfg["page_url"])
    html = raw.decode("utf-8")
    (OUT / "线上学生页.html").write_text(html, encoding="utf-8")
    tpl = (ROOT / "workbuddy-skill" / "assets" / "student.html").read_text(encoding="utf-8")
    check(st == 200 and "beike-book/1" in html, f"打得开（HTTP {st}，{len(raw) // 1024} KB），是书模式")
    for f in ("judge", "shortOf", "resultCode", "payload", "save"):
        x = js_func(html, f)
        check(x is not None and x == js_func(tpl, f), f"{f}() 和 assets/student.html 一字不差")
    m = re.search(r'"fieldMap"\s*:\s*(\{[^}]*\})', html)
    check(bool(m) and json.loads(m.group(1)) == contract.WEB_TO_COLUMN, "内置 fieldMap = contract.WEB_TO_COLUMN")

    print(f"3. 线上「我的复习」（{a.n} 个人）")
    plan = json.loads((home / "复习计划.json").read_text(encoding="utf-8")).get("每人", {})
    by = {}
    for k in sorted(plan, key=lambda k: (k.split("·")[0], len(plan[k]))):
        by.setdefault(k.split("·")[0], []).append(k)
    pick = list(dict.fromkeys([v[0] for v in by.values()] + [v[-1] for v in by.values()]))[:a.n]
    check(bool(pick), "复习计划里有人")
    for i, k in enumerate(pick, 1):
        cls, name = k.split("·", 1)
        st, raw = get(cfg["review_api"] + "?" + urllib.parse.urlencode({"班级": cls, "姓名": name}))
        live = [w["en"] for w in json.loads(raw).get("words", [])]
        check(sorted(live) == sorted(plan[k]), f"{cls} 第 {i} 个：线上 {len(live)} 个词，本机 learning.py 算 {len(plan[k])} 个")

    print("4. 浏览器真做一课（不提交）")
    page_json = OUT / "学生页.json"
    p = subprocess.run(["node", str(HERE / "live_student.mjs"), PW, cfg["page_url"], str(page_json)],
                       capture_output=True, text=True, timeout=300)
    print(p.stdout.rstrip())
    check(p.returncode == 0 and page_json.exists(), "Playwright 跑完" + ("" if p.returncode == 0 else "：" + p.stderr[-400:]))
    if page_json.exists():
        o = json.loads(page_json.read_text(encoding="utf-8"))
        check(not o["log"], "没有页面报错，也没有发出任何非 GET 请求")
        d = o["done"]
        row = collect.parse(d["code"])[0]
        col = {contract.WEB_TO_COLUMN[k]: v for k, v in d["payload"].items() if k in contract.WEB_TO_COLUMN}
        diff = [k for k in contract.BK2_ORDER if str(row.get(k, "")) != str(col.get(k, ""))]
        check(not diff, "群里发的结果码和表单预填，落到成绩表是同一行" + (f"（不一样：{diff}）" if diff else ""))
        check(len(d["prefill"]) < 16000, f"表单预填链接 {len(d['prefill'])} 字符，没超飞书上限")

    print("5. 约定检查")
    c = subprocess.run([sys.executable, str(HERE / "contracts.py")], capture_output=True, text=True)
    check(c.returncode == 0, "tests/contracts.py" + ("" if c.returncode == 0 else "\n" + c.stdout + c.stderr))

    print()
    if bad:
        sys.exit(f"✗ {len(bad)} 处没过。")
    print("✓ 线上验证全部通过（飞书只读，没写一行）。")


if __name__ == "__main__":
    main()
