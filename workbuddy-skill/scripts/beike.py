#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""老师说一句话，WorkBuddy 跑一条这个。老师自己不碰命令行。

老师的东西都记在 ~/.beike/ 里，说过一次就不用再说：
    名单.txt      几个班的名单（按班分段）
    config.json   表单链接、学生链接、上次发的是哪个单元
    复习计划.json 收 / 看 之后排好：每个人自己没拿下的词（进「我的复习」）+ 全班最卡的词（只给老师课上讲）
    复习设置.json 学期级：老师说的「去掉 / 加上」一直管用；「关掉」只管下一次发（同时写进飞书「复习设置」表）
    课/           这学期发过的每一课（学生页上一课一个分页，第 1 课 / 第 2 课 / …）
    发布/  成绩/  每次生成的网页和成绩表

    python3 beike.py 名单 [文件] [--班 高一3班]   存名单；不给文件就读粘贴进来的文字
    python3 beike.py 建表                          第一次用：在她飞书里建成绩表 + 交作业表单
    python3 beike.py 表单 <飞书表单分享链接>        已经有表单时用这个
    python3 beike.py 发 <词表.md> [--剧情 x.json] [--只生成]  这一课加进课目录，整个课目录重新发到同一个链接
    python3 beike.py 课 [列表 | 撤 <第几课> | 恢复 <第几课> | 改名 <第几课> <新名字>] [--只生成]
    python3 beike.py 群 <群名> [<群名>…]            记住班群名字（收作业只在这几个群里搜）
    python3 beike.py 收                            收作业：wechat-cli 抓群里的结果码 → 写进成绩表 → 报几个人没交 → 排好复习计划
    python3 beike.py 复习 [看 | 去掉 <词…> | 加上 <词…> | 关掉]   全班层面的复习设置；不用确认
    python3 beike.py 状态                          现在记着什么
    python3 beike.py 宠物 [开店 | 换/退 <名字> <配饰> | 送 <名字> <东西> | 装备 <单元> 头:英文:中文 … | 图片清单] [--演示]
                                                  宠物墙：用真成绩算豆子 → 孵化、长大；豆子在小卖部换配饰（开店 = 课上让学生自己挑）
    python3 beike.py 看 [--摘要] [--不打开] [--演示] 看板：从飞书拉成绩/名单/单元/词表 → ~/.beike/看板/ 下的网页、易错词榜、今日摘要
    python3 beike.py 收尾 [第几课] [--上传 <知识库>] [--演示]  一课结束：~/.beike/存档/<packId>/存档.md + 学情摘要.md；--上传 只列计划不上传
    python3 beike.py 期末 [--演示]                 期末复习：全班一直没拿下的词 + 每人自己没拿下的词 → 课目录里多一课
"""
import argparse, json, os, re, subprocess, sys, tempfile, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import roster  # noqa: E402
import lark_cli  # noqa: E402

HOME = Path(os.path.expanduser(os.environ.get("BEIKE_HOME", "~/.beike")))
ROSTER = HOME / "名单.txt"
CONFIG = HOME / "config.json"
REVIEW = HOME / "错题池.json"


def cfg():
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_cfg(**kw):
    c = cfg()
    c.update(kw)
    HOME.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")


def text_in(path, optional=False):
    if path:
        return Path(path).read_text(encoding="utf-8-sig")
    if sys.stdin.isatty():
        if optional:
            return ""
        sys.exit("没收到内容：给一个文件，或者把文字粘进来（管道传给这条命令）。")
    return sys.stdin.read()


# 成绩表的列、数字列、BK2 结果码的顺序：只在 contract.py 里写一份（学生页那头也按它对）。
# 表里的一行能还原成一串结果码，收作业时表单交的和群里发的走同一套统计。
from contract import SCORE_COLUMNS as FIELDS, SCORE_NUMS as NUMS, BK2_ORDER  # noqa: E402


def lark(*args, fmt="json"):
    cli = lark_cli.find_cli()
    p = subprocess.run([cli, *map(str, args), "--as", "user", "--format", fmt],
                       capture_output=True, text=True)
    for raw in (p.stdout, p.stderr):
        try:
            out = json.loads(raw)
            break
        except Exception:
            out = None
    if out and "ok" not in out and p.returncode == 0:
        return out                      # ndjson 模式直接给清单，没有 ok 外壳
    if not out or not out.get("ok"):
        err = (out or {}).get("error") or {}
        sys.exit("飞书拒绝了这一步：" + (err.get("message") or (p.stderr or p.stdout)[:500]))
    return out.get("data") or {}


def pull_rows(base, table):
    """把飞书一张表的所有行拉下来（table 可以是表 ID，也可以是表名）。
    lark-cli 的 --output 只认相对路径，所以临时目录建在 HOME 下面，跑完就删。"""
    import shutil
    HOME.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="pull-", dir=HOME))
    old = os.getcwd()
    try:
        os.chdir(HOME)
        rows, offset = [], 0
        while True:
            out = f"{tmp.name}/r{offset}.ndjson"
            d = lark("base", "+record-list", "--base-token", base, "--table-id", table,
                     "--offset", offset, "--limit", 2000, "--output", out, fmt="ndjson")
            with open(out, encoding="utf-8") as f:
                rows += [json.loads(l) for l in f if l.strip()]
            if not d.get("has_more"):
                break
            offset += 2000
    finally:
        os.chdir(old)
        shutil.rmtree(tmp, ignore_errors=True)
    return rows


def table_codes(base, table):
    """把成绩表里的每一行还原成一串 BK2 结果码。"""
    rows = pull_rows(base, table)

    def cell(v):
        if v is None:
            return ""
        if isinstance(v, float) and v.is_integer():
            v = int(v)
        if isinstance(v, list):
            v = "、".join(str(x.get("text", x)) if isinstance(x, dict) else str(x) for x in v)
        return str(v).replace("|", "/").replace("\n", " ").strip()
    return ["BK2|" + "|".join(cell(r.get(k)) for k in BK2_ORDER) for r in rows]


def py(script, *args):
    """跑同目录下的另一个脚本，失败就原样把它的话转出来。"""
    p = subprocess.run([sys.executable, str(HERE / script), *map(str, args)],
                       capture_output=True, text=True)
    if p.returncode:
        sys.exit((p.stderr or p.stdout).strip())
    return p.stdout


def summary(rs):
    return "、".join(f"{c or '没写班级'} {len(ns)} 人" for c, ns in rs.items())


# ── 名单 ────────────────────────────────────────────
def cmd_roster(a):
    raw = text_in(a.file)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False,
                                     encoding="utf-8") as f:
        f.write(raw)
    new = roster.read(f.name, default_cls=a.cls)
    os.unlink(f.name)
    if not any(new.values()):
        sys.exit("这段里没认出名字。一行一个人；几个班就「姓名,班级」或用「## 班级」分段。")
    if "" in new:
        sys.exit(f"有 {len(new[''])} 个人不知道是哪个班的（比如 {new[''][0]}）。"
                 "问老师这是哪个班，再用 --班 高一3班 重跑。")

    old = roster.read(ROSTER) if ROSTER.exists() else {}
    merged = dict(old)
    merged.update(new)                 # 这次给了哪个班就换哪个班，别的班不动
    HOME.mkdir(parents=True, exist_ok=True)
    ROSTER.write_text("".join(f"## {c}\n" + "".join(n + "\n" for n in ns) + "\n"
                              for c, ns in merged.items()), encoding="utf-8")
    replaced = [c for c in new if c in old]
    print(f"名单记好了：{summary(new)}。")
    if replaced:
        print(f"（{'、'.join(replaced)} 原来的名单换成了这份）")
    print(f"现在一共记着：{summary(merged)}。以后发作业、收作业都用这份，不用再给。")


# ── 建表 ────────────────────────────────────────────
def cmd_setup(a):
    c = cfg()
    if c.get("base") and not a.force:
        print(f"成绩表已经有了：{c.get('base_url', '')}\n交作业表单：{c.get('form', '')}")
        print("要重建加 --重建（旧表不会删，只是不再用）。")
        return
    fields = [{"name": n, "type": "number" if n in NUMS else "text"} for n in FIELDS]
    for f in fields:
        if f["type"] == "number":
            f["style"] = {"type": "plain", "precision": 0,
                          "percentage": False, "thousands_separator": False}
    d = lark("base", "+base-create", "--name", "背单词闯关成绩", "--time-zone", "Asia/Shanghai",
             "--table-name", "成绩", "--fields", json.dumps(fields, ensure_ascii=False))
    base, base_url = d["base"]["base_token"], d["base"]["url"]
    table = next(t["id"] for t in lark("base", "+table-list", "--base-token", base)["tables"]
                 if t["name"] == "成绩")
    form = lark("base", "+form-create", "--base-token", base, "--table-id", table,
                "--name", "交作业",
                "--description", "成绩已经自动填好了，直接点最下面的「提交」。")["id"]
    lark("base", "+view-set-visible-fields", "--base-token", base, "--table-id", table,
         "--view-id", form, "--json", json.dumps({"visible_fields": FIELDS}, ensure_ascii=False))
    A = ["--base-token", base, "--table-id", table, "--form-id", form]
    # 一次只能改一项。新表单默认「关闭 + 仅组织内」，学生会被要求登录飞书
    lark("base", "+form-share-update", *A, "--enabled=true")
    lark("base", "+form-share-update", *A, "--access-scope", "anyone")
    lark("base", "+form-share-update", *A, "--require-login=false")
    sh = lark("base", "+form-share-get", *A)
    if not sh.get("enabled") or sh.get("access_scope") != "anyone" or \
            (sh.get("settings") or {}).get("require_login"):
        sys.exit("表单没能设成「任何人不登录可填」：" + json.dumps(sh, ensure_ascii=False) +
                 "\n可能是学校飞书管理员关了对外分享。")
    save_cfg(base=base, table=table, base_url=base_url, form=sh["share_url"])
    print("成绩表建好了：" + base_url)
    print("交作业表单：" + sh["share_url"] + "（任何人不用登录就能交）")
    print("下次发新单元，学生做完点「交作业」，成绩就进这张表。")


# ── 表单 ────────────────────────────────────────────
def cmd_form(a):
    if "/share/base/" not in a.url:
        print("⚠️ 这个链接看着不像多维表格的「表单分享链接」，学生可能交不上。"
              "在多维表格里点表单视图 → 分享 → 复制链接。")
    save_cfg(form=a.url)
    print("表单链接记好了。以后学生做完点「交作业」，成绩直接进这张表。")


# ── 发 ──────────────────────────────────────────────
def review_words():
    try:
        return json.loads(REVIEW.read_text(encoding="utf-8")) or []
    except Exception:
        return []


def review_live_args(no_review=False):
    """方案 A：config 里有 review_api（妙搭后端地址）时，学生页里不放任何人的复习单，只放后端地址；
    学生点开「我的复习」才拿 班级 + 姓名 去查自己的。老师的「去掉 / 加上」后端从飞书「复习设置」表读，不写进网页。
    说过「关掉」（只管下一次发），或者 发 --不带错题，就不放这一格。"""
    api = cfg().get("review_api")
    if not api or no_review:
        return []
    import learning
    if learning.load_settings(HOME)["下次关掉"]:
        return []
    return ["--review-api", api]


def book_html(trial, no_review=False):
    """把课目录里的每一课做成一个学生页（第 1 课 / 第 2 课 / …），返回网页路径和一句「现在一共几课」。
    trial=True（只生成）时，只生成过、还没真发的课也放进去。"""
    import units
    out_dir = HOME / "发布"
    out_dir.mkdir(parents=True, exist_ok=True)
    html = out_dir / f"背单词闯关-{time.strftime('%m%d-%H%M%S')}.html"
    args = ["--book", HOME / "课", "-o", html, "--roster", ROSTER, "--no-hint"]
    if cfg().get("form"):
        args += ["--form", cfg()["form"]]
    if trial:
        args += ["--include-trial"]
    args += review_live_args(no_review)
    print(py("publish.py", *args).rstrip())
    es = [e for e in units.lessons(HOME) if trial or not e.get("试做")]
    line = (f"现在学生页上一共 {len(es)} 课，最新的是{units.label(es[-1])}"
            + (f"「{es[-1]['标题']}」" if es[-1].get("类型") != "期末" else "") + "。") if es else ""
    return html, line


def go_live(html):
    """发到那一个固定的学生链接（链接不变）。
    config 里有 page_app（全栈应用 id）和 page_url 时：把整页 HTML 插进那个应用库里的 student_page 表，
    学生链接 page_url（…/student-api/page）读最新一行，不用重新发布应用，十几秒。
    没配就停下来报错，不会自己去新建应用。"""
    c = cfg()
    if not (c.get("page_app") and c.get("page_url")):
        sys.exit("config 里没有 page_app / page_url，不知道学生页发到哪个妙搭全栈应用。\n"
                 f"网页已经生成好了：{html}\n"
                 "在 ~/.beike/config.json 里填上全栈应用的 app_id（page_app）和学生链接（page_url，"
                 "…/student-api/page），再跑一次「发」。")
    return page_to_db(Path(html), c["page_app"], c["page_url"])


def page_to_db(html, app, url):
    """插一行 student_page，留最近 30 版。设了 BEIKE_HOME（演示 / 测试）时只写开发库，学生链接不受影响。"""
    import base64, hashlib, tempfile, urllib.request
    real = HOME == Path(os.path.expanduser("~/.beike"))
    env = "online" if real else "dev"
    raw = html.read_bytes()
    note = f"{html.name} {time.strftime('%Y-%m-%d %H:%M')}"
    sql = ("INSERT INTO student_page (html, note) VALUES (convert_from(decode('"
           + base64.b64encode(raw).decode() + "', 'base64'), 'UTF8'), '" + note.replace("'", "") + "');\n"
           "DELETE FROM student_page WHERE id NOT IN (SELECT id FROM student_page ORDER BY id DESC LIMIT 30);\n")
    with tempfile.TemporaryDirectory(dir=HOME) as d:      # lark-cli 的 --file 只收当前目录下的相对路径
        Path(d, "page.sql").write_text(sql, encoding="utf-8")
        p = subprocess.run([lark_cli.find_cli(), "apps", "+db-execute", "--app-id", app, "--environment", env,
                            "--file", "page.sql", "--yes", "--as", "user"], capture_output=True, text=True, cwd=d)
    try:
        ok = json.loads(p.stdout).get("ok")
    except Exception:
        ok = False
    if not ok:
        sys.exit("学生页没写进去：" + (p.stderr or p.stdout)[:500])
    if not real:
        print(f"（BEIKE_HOME={HOME}：只写进了开发库，学生链接没动。）")
        return url
    want = hashlib.sha256(raw).hexdigest()               # 线上有 10 秒缓存，等它换成这一版
    for _ in range(12):
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                if hashlib.sha256(r.read()).hexdigest() == want:
                    break
        except Exception:
            pass
        time.sleep(3)
    else:
        print("⚠️ 写进去了，但学生链接还没换成这一版。过一分钟自己点开看一下。")
    save_cfg(link=url)
    return url


def cmd_send(a):
    import units, learning
    if not ROSTER.exists():
        sys.exit("还没有名单。先问老师要几个班的名单（从学校系统导出的就行），"
                 "用「beike.py 名单」存一次。")
    out_dir = HOME / "发布"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%m%d-%H%M")
    pack = out_dir / f"pack-{stamp}.json"

    # 复习只在每人的「我的复习」里。新课本身不再塞复习词（全班最卡的词只给老师课上讲），
    # 所以不再给 build_pack 传 --review；错题池只留着给老师看。
    plan = None if a.no_review else learning.load_plan(HOME)
    off = learning.load_settings(HOME)["下次关掉"]       # 「关掉」只管这一次发
    use_plan = bool(plan) and not off
    args = [a.wordlist, "-o", pack]
    if a.episode:
        args += ["--episode", a.episode]
    py("build_pack.py", *args)
    pk = json.loads(pack.read_text(encoding="utf-8"))
    title, pack_id = pk.get("title", "背单词闯关"), pk.get("packId", "")
    entry = units.add(pk, a.wordlist, 试做=a.no_deploy, home=HOME)
    live = bool(cfg().get("review_api"))
    if live:
        units.set_review("", {}, {}, HOME)          # 方案 A：页面里不放任何人的单子，点开现查
    elif off or not use_plan:
        units.set_review("", {}, {}, HOME)
    else:
        day = str(plan.get("生成于", ""))[:10].replace("-", "") or time.strftime("%Y%m%d")
        mine = {w for ws in plan.get("每人", {}).values() for w in ws}     # 只放有人要做的词
        units.set_review(f"review-{day}", {w: z for w, z in plan.get("中文", {}).items() if w in mine},
                         plan.get("每人", {}), HOME)

    html, line = book_html(a.no_deploy, a.no_review)
    if a.no_deploy:
        print(f"\n网页生成好了，没发布：{html}")
        print(f"这一课是{units.label(entry)}。{line}")
        print("（只生成的网页里有这一课；学生链接没动。真发的时候再说一次「发」。）")
        return

    url = go_live(html)
    form = cfg().get("form", "")
    units.mark_sent(pack_id, HOME)
    if live and cfg().get("base"):
        # 后端现查要知道这一课的题号对哪个词：单元 / 词表 两张表写进成绩表所在的多维表格（只在真发时写）
        try:
            import review_rows
            n = review_rows.push_all(lark, pull_rows, cfg()["base"], HOME)
            print(f"词表：{n} 课的词和题号写进了飞书（「我的复习」现查要用；已经有的行只更新）。")
        except (SystemExit, Exception) as e:          # noqa: BLE001 — 学生链接已经发好了，这一步失败不能挡
            print(f"⚠️ 词表没写进飞书（{e}）。「我的复习」还能查，只是这一课的词算不进去，下次发会再补。")
    save_cfg(last=title, last_pack=pack_id, last_at=time.strftime("%Y-%m-%d %H:%M"))
    if off:                                        # 「关掉」只管这一次发，发完自动恢复
        st = learning.load_settings(HOME)
        st["下次关掉"] = False
        learning.save_settings(st, HOME)
        if plan:
            learning.apply_settings(plan, HOME)
            learning.save_plan(plan, HOME)
    rs = roster.read(ROSTER)

    print("\n══ 发好了 ══")
    print(f"单元：{title}（{units.label(entry)}）")
    print(line + "以前的课学生还能点开做、能交。")
    print(f"班级：{summary(rs)}（同一个链接，学生选自己名字，班级自动跟着走）")
    if live and review_live_args(a.no_review):
        print("「我的复习」：学生页最前面一格，每个学生点开时现查自己没拿下的词（网页里不放任何人的单子）。新课里没加复习词。")
    elif live or off:
        print("「我的复习」：这次关掉了，学生页上没有（下次发自动恢复）。")
    elif use_plan and plan.get("每人"):
        print(f"「我的复习」：{len(plan['每人'])} 个学生各有自己没拿下的词，在学生页最前面一个分页。新课里没加复习词。")
    if use_plan and plan.get("全班"):
        print(f"全班最卡的词（课上讲，没放进网页）：{'、'.join(plan['全班'][:5])}")
    if not form:
        print("⚠️ 还没给表单链接：学生做完只能复制一串结果码发群里，你再说「收一下作业」。")
    print("\n下面这段直接复制，发到每个班群：\n")
    print("────────")
    print(f"【背单词闯关】{title}")
    print(url)
    print("点开选自己的名字就能开始，做完点「交作业」。" + ("" if cfg().get("page_app") else "页面右上角的「登录」不用管。"))
    print("────────")
    print("\n发群之前，自己先用手机流量、从微信里点开做一遍，交一次作业看表里有没有多一行。")


# ── 收 ──────────────────────────────────────────────
def find_wechat_cli():
    import shutil, glob
    hit = shutil.which("wechat-cli")
    if hit:
        return hit
    for g in ("~/.nvm/versions/node/*/bin/wechat-cli", "/opt/homebrew/bin/wechat-cli",
              "/usr/local/bin/wechat-cli"):
        for x in sorted(glob.glob(os.path.expanduser(g)), reverse=True):
            return x
    return None


def wechat_codes(since, groups):
    """用 wechat-cli（只读）在微信群里搜 BK2| 开头的结果码。只取结果码，聊天别的内容一概不留。
    返回 (结果码列表, 一句说明)。没装 / 没初始化就返回空，不让「收」整个失败。"""
    cli = find_wechat_cli()
    if not cli:
        return [], "这台电脑还没装 wechat-cli，群里的结果码这次没抓（第一次用让 WorkBuddy 按 wechat-cli-readonly-skill 装好）。"
    codes, offset = [], 0
    while True:
        cmd = [cli, "search", "BK2|", "--start-time", since, "--limit", "500",
               "--offset", str(offset), "--format", "json"]
        for g in groups:
            cmd += ["--chat", g]
        p = subprocess.run(cmd, capture_output=True, text=True)
        try:
            d = json.loads(p.stdout)
        except Exception:
            return codes, "wechat-cli 没读出来（多半是还没 init，或微信版本不对）：" + (p.stderr or p.stdout).strip()[:200]
        res = d.get("results") or []
        for line in res:
            line = line if isinstance(line, str) else json.dumps(line, ensure_ascii=False)
            codes += re.findall(r"BK2\|[^\n\r]*", line)
        if len(res) < 500:
            break
        offset += 500
    where = "、".join(groups) if groups else "所有微信聊天"
    return codes, f"微信群（{where}，{since} 以来）抓到 {len(codes)} 条结果码。"


def to_record(row):
    rec = {}
    for k in FIELDS:
        v = (row.get(k) or "").strip()
        if not v:
            continue
        if k in NUMS:
            try:
                v = int(float(v))
            except ValueError:
                continue
        rec[k] = v
    return rec


def push_to_table(c, rows):
    for i in range(0, len(rows), 200):
        lark("base", "+record-batch-create", "--base-token", c["base"], "--table-id", c["table"],
             "--json", json.dumps({"create_records": [to_record(r) for r in rows[i:i + 200]]},
                                  ensure_ascii=False))


def cmd_collect(a):
    import collect
    c = cfg()
    pasted = text_in(a.file, optional=True)
    since = a.since or (c.get("last_at") or time.strftime(
        "%Y-%m-%d", time.localtime(time.time() - 7 * 86400)))[:10]

    chat_text = pasted
    if not a.no_wechat:
        codes, note = wechat_codes(since, c.get("groups") or [])
        print(note)
        chat_text += "\n" + "\n".join(codes)
    chat_rows = collect.parse(chat_text)

    if c.get("base"):
        table = table_codes(c["base"], c["table"])
        key = lambda r: (r["班级"], r["姓名"], r["内容包"], r["第几次"])
        have = {key(r) for r in collect.parse("\n".join(table))}
        new = [r for r in chat_rows if key(r) not in have]
        if new:
            push_to_table(c, new)
            print(f"群里的 {len(new)} 条新结果码已经替老师写进成绩表（表里原来有的不重复写）。")
        raw = "\n".join(table) + "\n" + "\n".join(
            "BK2|" + "|".join(r[k] for k in BK2_ORDER) for r in new)
        print(f"成绩表里现在一共 {len(table) + len(new)} 条。")
    elif chat_rows:
        raw = chat_text
    else:
        sys.exit("还没有成绩表，群里也没抓到结果码（BK2| 开头的那串）。")

    d = HOME / "成绩"
    d.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False,
                                     encoding="utf-8") as f:
        f.write(raw)
    csv = d / f"成绩-{time.strftime('%Y%m%d-%H%M')}.csv"
    args = [f.name, "-o", csv]
    if c.get("last_pack") and not a.all:
        args += ["--pack", c["last_pack"]]
        print(f"只看这一单元：{c.get('last', c['last_pack'])}（要看全部加 --全部）")
    if ROSTER.exists():
        args += ["--roster", ROSTER]
    try:
        print(py("collect.py", *args).rstrip())
    finally:
        os.unlink(f.name)
    print(f"\n成绩表存在：{csv}")
    print("\n" + draft_review(collect.parse(raw), "收"))


def draft_review(records, src):
    """收 / 看 之后：从全部成绩 + 课目录现算每个人没拿下的词，起草下次的复习计划。返回给老师的一两句话。"""
    import learning, build_pack
    known = build_pack.load_known(HOME / "发布", HOME / "课")
    model = learning.compute(records, home=HOME, zh={en: z for en, z in known.values()})
    return "复习：" + learning.draft_plan(model, src, HOME)


# ── 课（课目录：学生页上的分页）──────────────────────────
def cmd_units(a):
    import units
    act, rest = a.action or "列表", a.args
    if act == "列表":
        es = units.lessons(HOME, 含撤了=True)
        if not es:
            print("课目录里还没有课。说「发 <词表>」发第一课。")
            return
        for e in es:
            tag = "（撤了，学生页上看不到）" if e.get("撤了") else "（只生成过，还没真发）" if e.get("试做") else ""
            print(f"{units.label(e)}　{e.get('标题', '')}　{str(e.get('发布时间', ''))[:10]}{tag}")
        rv = units.load(HOME).get("复习")
        if rv:
            print(f"我的复习　{rv.get('人数', 0)} 个学生有自己要复习的词（放在最前面，不占第几课）")
        return
    if act not in ("撤", "恢复", "改名"):
        sys.exit("「课」后面跟：列表 / 撤 <第几课> / 恢复 <第几课> / 改名 <第几课> <新名字>")
    if not rest or (act == "改名" and len(rest) < 2):
        sys.exit("说是第几课，比如「课 撤 2」" + ("，改名还要给新名字" if act == "改名" else "") + "。")
    e = units.rename(rest[0], " ".join(rest[1:]), HOME) if act == "改名" else \
        units.hide(rest[0], HOME, undo=act == "恢复")
    if not e:
        sys.exit(f"课目录里没有「{rest[0]}」。说「课 列表」看看有哪几课。")
    did = {"撤": "撤下来了（成绩和存档都还在，号不重排）", "恢复": "放回学生页了",
           "改名": f"改名叫「{e['标题']}」了"}[act]
    print(f"{units.label(e)}{did}。")
    html, line = book_html(a.no_deploy)
    if a.no_deploy:
        print(f"网页生成好了，没发布：{html}\n{line}")
        return
    go_live(html)
    print(f"学生链接已经更新，链接不变。{line}")


# ── 复习（全班层面的设置：去掉 / 加上 一直管用，关掉只管下一次发；不用确认）────────
def cmd_review(a):
    import learning
    act, ws = a.action or "看", [w.strip() for w in a.words if w.strip()]
    st = learning.load_settings(HOME)
    if act in ("去掉", "加上"):
        if not ws:
            sys.exit(f"说要{act}哪几个词，比如「复习 {act} devote」。")
        other = "加上" if act == "去掉" else "去掉"
        low = {w.lower() for w in ws}
        st[other] = [w for w in st[other] if w.lower() not in low]
        st[act] = st[act] + [w for w in ws if w.lower() not in {x.lower() for x in st[act]}]
        if act == "加上":
            import build_pack
            known = build_pack.load_known(HOME / "发布", HOME / "课")
            miss = []
            for w in ws:
                if w.lower() in known:
                    st["中文"][w] = known[w.lower()][1]
                elif not st["中文"].get(w):
                    miss.append(w)
            if miss:
                print(f"注意：{'、'.join(miss)} 以前没发过，找不到中文，出不了题，「我的复习」里不会有它。")
    elif act == "关掉":
        st["下次关掉"] = True
    elif act != "看":
        sys.exit("「复习」后面跟：看 / 去掉 <词…> / 加上 <词…> / 关掉")
    p = learning.load_plan(HOME)
    if act != "看":
        learning.save_settings(st, HOME)
        if p:
            learning.apply_settings(p, HOME)
            learning.save_plan(p, HOME)
        c = cfg()
        if act in ("去掉", "加上") and c.get("base"):
            try:
                import review_rows
                review_rows.push_settings(lark, pull_rows, c["base"], st)
                print("已经写进飞书「复习设置」表，学生下次点开「我的复习」就按这个来。")
            except (SystemExit, Exception) as e:          # noqa: BLE001
                print(f"⚠️ 没写进飞书「复习设置」表（{e}）。这台电脑上记下了，下次再说一次「复习」会再写。")
    if p:
        print(learning.plan_sentence(p))
    elif st["下次关掉"]:
        print("下次发新课不带「我的复习」，发完那一次就自动恢复。")
    if st["去掉"]:
        print("这学期不用复习的：" + "、".join(st["去掉"]))
    if st["加上"]:
        print("这学期给还没拿下的人都加上的：" + "、".join(st["加上"]))


def soft_lark(*args):
    """读点可有可无的东西（比如 base 名字）。失败就算了，不让整条命令停下。"""
    try:
        return lark(*args)
    except SystemExit:
        return {}


def expected_by_pack(home):
    """期末那种按人出词的课：谁有自己的词谁才应该交（没词的人学生页上看不到这一课，不能算没交）。
    {packId: [班·名…]}；全班都有词的（all 不空）不放进来，照常按名单算。「我的复习」不算课，也不放。"""
    import units
    out = {}
    for pid, pk in units.all_packs(home).items():
        if pk.get("schema") != "beike-words/1" or pk.get("kind") == "复习" or str(pid).startswith("review-"):
            continue
        if not pk.get("all"):
            out[pid] = sorted(k for k, ws in (pk.get("who") or {}).items() if ws)
    return out


def look_extras(records, words, demo, look):
    """看板要的课目录、收尾了没有；look=True 时再从 learning.py 现算每个人的词，并起草复习计划（「看」跑完就起草，
    和「收」一样）。演示数据的课目录和复习计划放在 演示/ 下面，不混进老师真的。接不上就少一块，不挡看板。"""
    import archive
    home, out, notes = cat_home(demo), {}, []
    try:
        out["catalog"] = archive.catalog(home)[0]
    except Exception as e:               # noqa: BLE001 — 课目录读不了，就按成绩里的单元排
        notes.append(f"课目录读不了（{type(e).__name__}），按成绩表里的单元排。")
    adir = HOME / "存档" / ("演示" if demo else "")
    out["archived"] = [d.name for d in adir.iterdir() if (d / "存档.md").exists()] if adir.is_dir() else []
    try:
        import learning
        out["expected"] = expected_by_pack(home)
        vocab, zh = {}, {}
        for w in words:
            en, pid = str(w.get("词") or "").strip(), str(w.get("内容包") or "").strip()
            if en and pid:
                vocab.setdefault(pid, []).append(en)
                zh.setdefault(en, str(w.get("中文") or ""))
        if not demo:                     # 和 draft_review 一样，再用发过的课补中文（每人的复习词要有中文）
            import build_pack
            for en, z in build_pack.load_known(HOME / "发布", HOME / "课").values():
                if z and not zh.get(en):
                    zh[en] = z
        out["learn"] = learning.compute(records, home=home, vocab=vocab, zh=zh)
        if look:
            learning.draft_plan(out["learn"], "看", home)   # 复习情况只讲整体，写在摘要里
            out["plan"] = learning.load_plan(home)
            if isinstance(out["plan"], dict):       # 只给看板用，不写回文件
                out["plan"]["_现查"] = bool(cfg().get("review_api"))
    except Exception as e:               # noqa: BLE001
        notes.append(f"每个人的词和复习计划这次没算出来（{type(e).__name__}: {e}），看板其他部分照常。")
    return out, notes


def pull_all(demo, look=False):
    """看板和宠物墙共用：从飞书拉 成绩 + 名单/单元/词表（有就拉），算出看板模型。只读（look=True 时会起草复习计划）。"""
    import dashboard
    from collections import OrderedDict
    c = cfg()
    base = c.get("demo_base") if demo else c.get("base")
    if not base:
        sys.exit("还没有演示数据的表（config 里没有 demo_base）。" if demo else
                 "还没有成绩表。先「beike.py 建表」，或者用「beike.py 表单」接上已有的表。")
    tables = {t["name"]: t["id"] for t in lark("base", "+table-list", "--base-token", base)["tables"]}
    score = (None if demo else c.get("table")) or tables.get("成绩")
    if not score:
        sys.exit("这个多维表格里找不到「成绩」表。")
    records = pull_rows(base, score)
    pulled = ["成绩"]

    rs, roster_from = OrderedDict(), ""
    if "名单" in tables:
        for r in pull_rows(base, tables["名单"]):
            cls, name = str(r.get("班级") or "").strip(), str(r.get("姓名") or "").strip()
            if name and name not in rs.setdefault(cls, []):
                rs[cls].append(name)
        roster_from, _ = "飞书「名单」表", pulled.append("名单")
    if not any(rs.values()) and ROSTER.exists():
        rs, roster_from = roster.read(ROSTER), "这台电脑上存的名单"
    if not any(rs.values()):
        for r in records:
            n = str(r.get("姓名") or "").strip()
            if n and n not in rs.setdefault(str(r.get("班级") or "").strip(), []):
                rs[str(r.get("班级") or "").strip()].append(n)
        roster_from = "成绩表里出现过的人（没有名单，所以「谁没交」算不出来）"
    no_roster = roster_from.startswith("成绩表")
    units = pull_rows(base, tables["单元"]) if "单元" in tables else []
    words = pull_rows(base, tables["词表"]) if "词表" in tables else []
    pulled += [t for t, v in (("单元", units), ("词表", words)) if v]

    info = soft_lark("base", "+base-get", "--base-token", base)
    name = (info.get("base") or info).get("name", "") if isinstance(info, dict) else ""
    extra, notes = look_extras(records, words, demo, look)
    model = dashboard.compute(records, rs, units, words, meta={
        "base_name": name or "背单词闯关成绩", "demo": bool(demo or "假数据" in name),
        "roster_from": roster_from, "tables": pulled, "no_roster": no_roster, "notes": notes}, **extra)
    return model, records, pulled, roster_from


def build_look(demo):
    """拉数据、写看板（成绩和宠物在同一页）、易错词榜、今日摘要。「看」和「宠物」都用它。"""
    import dashboard
    model, records, pulled, roster_from = pull_all(demo, look=True)
    out_dir = HOME / "看板"
    out_dir.mkdir(parents=True, exist_ok=True)
    look_pets(model, demo, out_dir)
    day = time.strftime("%Y%m%d")
    md = dashboard.wrong_words_md(model)
    md_path = out_dir / f"易错词榜-{day}.md"
    md_path.write_text(md, encoding="utf-8")
    model["meta"]["wrong_md"] = md
    text = dashboard.summary_text(model)
    (out_dir / "今日摘要.txt").write_text(text + "\n", encoding="utf-8")
    page = out_dir / "看板.html"
    page.write_text(dashboard.render_html(model, (HERE.parent / "assets" / "dashboard.html")
                                          .read_text(encoding="utf-8")), encoding="utf-8")
    for p in (page, md_path, out_dir / "今日摘要.txt"):
        os.chmod(p, 0o600)               # 有学生名字，只给本人读
    return model, records, pulled, roster_from, page, md_path, text


def cmd_look(a):
    model, records, pulled, roster_from, page, md_path, text = build_look(a.demo)
    if a.summary_only:
        print(text)
        return
    print(f"从飞书拉了：{'、'.join(pulled)}（{len(records)} 条提交）。名单用的是{roster_from}。")
    print(f"看板：{page}")
    print(f"易错词榜：{md_path}")
    print("\n" + text)
    for n in model["meta"].get("notes") or []:
        print("\n" + n)
    shop = None if a.no_shop else start_board_shop(a.demo)
    if shop:
        print(f"\n小卖部也开了，就在看板的「宠物」页签里：学生点自己的宠物就能换配饰。"
              f"看板地址（只有这台电脑能打开）：{shop}board\n没人用 30 分钟自动关；关了再说一次「看一下成绩」。")
    if not a.no_open and sys.platform == "darwin":
        subprocess.run(["open", (f"{shop}board" if shop else page.as_uri()) + ("#宠物" if a.pets else "")])


SHOP_PID = "小卖部.pid"


def stop_board_shop():
    """上一次「看」开的小卖部还在跑，先让它正常关门（关门时会同步宠物账本），再开新的，免得两个同时往账本里记。"""
    f = HOME / "看板" / SHOP_PID
    pid = read_json(f, {}).get("pid")
    f.unlink(missing_ok=True)
    if not pid:
        return
    cmd = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True).stdout
    if "beike.py" not in cmd or "--跟看板" not in cmd:
        return
    import signal
    os.kill(pid, signal.SIGTERM)
    for _ in range(60):
        time.sleep(0.5)
        if subprocess.run(["ps", "-p", str(pid)], capture_output=True).returncode:
            return


def start_board_shop(demo):
    """在后台开小卖部（本机 127.0.0.1 + 随机口令），返回它的地址；看板也从这个地址打开。
    口令只在这个进程和打开的网页里，不写进任何文件。开不起来就返回 None，看板照样用本地文件打开。"""
    import threading
    stop_board_shop()
    out_dir = HOME / "看板"
    log = out_dir / "小卖部.log"
    log.touch(mode=0o600, exist_ok=True)
    cmd = [sys.executable, str(Path(__file__).resolve()), "宠物", "开店", "--跟看板", "--不打开"] + (["--演示"] if demo else [])
    with open(log, "a", encoding="utf-8") as err:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err, stdin=subprocess.DEVNULL,
                                text=True, start_new_session=True)
    got = {}

    def read():
        for line in proc.stdout:
            line = line.rstrip("\n")
            if line.startswith("小卖部开了："):
                got["url"] = line.split("：", 1)[1].strip()
                return
            if line.strip():
                print(line)
    t = threading.Thread(target=read, daemon=True)
    t.start()
    t.join(120)
    if not got.get("url"):
        print(f"⚠️ 小卖部这次没开起来（细节在 {log}），看板照常打开；要开就说「开小卖部」。")
        return None
    write_json(out_dir / SHOP_PID, {"pid": proc.pid, "开的时间": time.strftime("%Y-%m-%d %H:%M")})
    return got["url"]


def look_pets(model, demo, out_dir):
    """看板和宠物墙放在一页：看板最上面有「成绩 / 宠物」两个页签。宠物墙在这里只读本机记录，
    不同步飞书、不更新「上次」（「新孵出来」照旧和上次跑「宠物」时比）。算不出来就不放这一页签，不挡看板。"""
    import dashboard, pets
    try:
        d = pet_dir(demo)
        pm = pets.compute(model, pet_state(d), pet_term(), read_json(d / "上次.json", {}))
        prefix = os.path.relpath(pet_images(), out_dir).replace(os.sep, "/") + "/"
        page = pets.render_html(pm, (HERE.parent / "assets" / "pets.html").read_text(encoding="utf-8"),
                                pets.image_urls(pm, pet_images(), prefix))
        model["pets"] = dashboard.pets_view(pm, page)
    except Exception as e:               # noqa: BLE001
        model["meta"].setdefault("notes", []).append(f"宠物这次没算出来（{type(e).__name__}: {e}），看板其他部分照常。")


# ── 宠物 ────────────────────────────────────────────
def pet_dir(demo):
    d = HOME / "宠物" / ("演示" if demo else "")
    d.mkdir(parents=True, exist_ok=True)
    return d


def read_json(p, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(p, obj):
    Path(p).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.chmod(p, 0o600)


PET_FILES = {"送": "送的.json", "装备": "装备.json", "换": "换的.json", "戴": "穿戴.json"}


def pet_state(d):
    return {k: read_json(d / f, {} if k in ("装备", "戴") else []) for k, f in PET_FILES.items()}


def save_pet_state(d, state, *keys):
    for k in keys:
        write_json(d / PET_FILES[k], state.get(k, {} if k in ("装备", "戴") else []))


def pet_images():
    """把技能自带的图（assets/pets/）补进 ~/.beike/宠物/图/。已经有的不覆盖，老师换过的图保留。"""
    import shutil
    dst = HOME / "宠物" / "图"
    dst.mkdir(parents=True, exist_ok=True)
    src = HERE.parent / "assets" / "pets"
    if src.is_dir():
        for f in src.iterdir():
            if f.suffix == ".png" and not (dst / f.name).exists():
                shutil.copy2(f, dst / f.name)
    return dst


def import_pet_images(src, dst, overwrite=False):
    """Codex 画的图一般 1000 多像素、1 MB 左右；缩小以后再放进图片目录（宠物 360、配饰 240、背景 900）。
    只认 egg-/item-/scene-/<宠物>-baby|teen|adult.png 这样的文件名。用 macOS 自带的 sips，不用装东西。"""
    import shutil
    dst.mkdir(parents=True, exist_ok=True)
    n = 0
    for f in sorted(Path(src).glob("*.png")):
        if not re.fullmatch(r"(egg-[a-z]+|[a-z]+-(baby|teen|adult)|item-[a-z0-9-]+|scene-[a-z0-9-]+)\.png", f.name):
            continue
        out = dst / f.name
        if out.exists() and not overwrite:
            continue
        size = 900 if f.name.startswith("scene-") else 240 if f.name.startswith("item-") else 360
        r = subprocess.run(["sips", "-Z", str(size), str(f), "--out", str(out)], capture_output=True) \
            if shutil.which("sips") else None
        if not r or r.returncode:
            shutil.copy2(f, out)
        n += 1
    return n


def pet_term():
    return cfg().get("学期") or (time.strftime("%Y") + ("秋" if int(time.strftime("%m")) >= 8 else "春"))


def find_pet(pm, name, cls):
    hits = [p for p in pm["pets"] if p["name"] == name and (not cls or p["cls"] == cls)]
    if not hits:
        sys.exit(f"名单里找不到「{name}」" + (f"（{cls}）" if cls else "") + "。")
    if len(hits) > 1:
        sys.exit(f"「{name}」在 {'、'.join(p['cls'] for p in hits)} 都有，加上 --班 说是哪个班。")
    return hits[0]


def find_item(pm, word):
    w = word.strip().lower()
    it = next((x for x in pm["shop"] if w in (x["id"], x["en"].lower(), x["zh"])), None)
    if not it:
        sys.exit(f"小卖部里没有「{word}」。有：" + "、".join(f"{x['zh'] or x['en']}" for x in pm["shop"]))
    return it


# ── 宠物账本（飞书多维表格里的一张表）──────────────────
# 本机的 换的/穿戴/送的/装备.json 说了算；账本是它在飞书上的备份和流水，只往里加行，不改不删。
# 每次「宠物」开头、改完东西、小卖部关门时都对一遍：本机有、账本没有的，补一行；
# 本机这四个文件一个都没有（换电脑、误删）而账本里有东西，就从账本恢复。
LEDGER = "宠物账本"
LEDGER_FIELDS = ["说明", "时间", "班级", "姓名", "动作", "东西", "中文", "豆子", "备注", "序号", "数据"]


def ledger_table(base, create=True):
    def find():
        return next((t["id"] for t in lark("base", "+table-list", "--base-token", base)["tables"]
                     if t["name"] == LEDGER), None)
    tid = find()
    if tid or not create:
        return tid
    fields = [{"name": n, "type": "number" if n in ("豆子", "序号") else "text"} for n in LEDGER_FIELDS]
    for f in fields:
        if f["type"] == "number":
            f["style"] = {"type": "plain", "precision": 0, "percentage": False, "thousands_separator": False}
    lark("base", "+table-create", "--base-token", base, "--name", LEDGER,
         "--fields", json.dumps(fields, ensure_ascii=False))
    print(f"在多维表格里建好了「{LEDGER}」表：谁换了什么、花了几颗豆子，都记在这里。")
    return find()


def ledger_text(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, list):
        v = "".join(str(x.get("text", x)) if isinstance(x, dict) else str(x) for x in v)
    return str(v)


def ledger_replay(rows):
    """按序号把账本一行行重放，得到账本眼里的「现在」：换的、穿戴、送的、装备。"""
    st = {"换": [], "戴": {}, "送": [], "装备": {}}

    def drop(xs, x, keys):
        for i, y in enumerate(xs):
            if all(y.get(k) == x.get(k) for k in keys):
                return xs.pop(i)
    for r in sorted(rows, key=lambda r: float(r.get("序号") or 0)):
        try:
            x = json.loads(ledger_text(r.get("数据")) or "{}")
        except ValueError:
            continue
        act = ledger_text(r.get("动作"))
        if act == "换":
            st["换"].append(x)
        elif act == "退":
            drop(st["换"], x, ("cls", "name", "id"))
        elif act == "送":
            st["送"].append(x)
        elif act == "撤回":
            drop(st["送"], x, ("cls", "name", "item", "date"))
        elif act == "戴" and x.get("key") and x.get("slot"):
            st["戴"].setdefault(x["key"], {})[x["slot"]] = x.get("id") or ""
        elif act == "装备" and x.get("unit"):
            if x.get("items"):
                st["装备"][x["unit"]] = x["items"]
            else:
                st["装备"].pop(x["unit"], None)
    return st


def ledger_diff(local, led, names):
    """本机和账本不一样的地方，变成要补进账本的行（按顺序）。names：配饰 id → (英文, 中文)。"""
    import pets
    out, now = [], time.strftime("%Y-%m-%d %H:%M")
    canon = lambda x: json.dumps(x, ensure_ascii=False, sort_keys=True)

    def bag(xs):
        b = {}
        for x in xs:
            b.setdefault(canon(x), []).append(x)
        return b

    def row(act, x, cls, name, thing, zh, beans, note, when=""):
        en, zh2 = names.get(thing, (thing, ""))
        zh = zh or zh2
        word = {"换": "换了", "退": "退了", "送": "老师送了", "撤回": "撤回了老师送的", "戴": "戴上", "装备": "上架"}[act]
        say = f"{cls} {name} {word} {zh or en}".strip() if act != "装备" else f"{x['unit']} 的装备：{note}"
        if act == "戴" and not thing:
            say = f"{cls} {name} 把{pets.SLOT_ZH.get(x['slot'], x['slot'])}的摘了"
        if beans:
            say += f"（{'+' if beans > 0 else ''}{beans} 颗）"
        out.append({"说明": say, "时间": when or now, "班级": cls, "姓名": name, "动作": act,
                    "东西": en, "中文": zh, "豆子": beans, "备注": note, "数据": canon(x)})

    lb, rb = bag(local.get("换", [])), bag(led["换"])
    for k in sorted(set(lb) | set(rb)):
        a_, b_ = lb.get(k, []), rb.get(k, [])
        for x in a_[len(b_):]:
            row("换", x, x.get("cls", ""), x.get("name", ""), x.get("id", ""), "", -int(x.get("price") or 0), "", x.get("date", ""))
        for x in b_[len(a_):]:
            row("退", x, x.get("cls", ""), x.get("name", ""), x.get("id", ""), "", int(x.get("price") or 0), "")
    lb, rb = bag(local.get("送", [])), bag(led["送"])
    for k in sorted(set(lb) | set(rb)):
        a_, b_ = lb.get(k, []), rb.get(k, [])
        for x in a_[len(b_):]:
            row("送", x, x.get("cls", ""), x.get("name", ""), x.get("item", ""), x.get("item", ""), pets.GIFT_BEANS,
                x.get("reason", ""), x.get("date", ""))
        for x in b_[len(a_):]:
            row("撤回", x, x.get("cls", ""), x.get("name", ""), x.get("item", ""), x.get("item", ""), -pets.GIFT_BEANS, "")
    lw, rw = local.get("戴", {}), led["戴"]
    for key in sorted(set(lw) | set(rw)):
        for slot in sorted(set(lw.get(key, {})) | set(rw.get(key, {}))):
            v = lw.get(key, {}).get(slot) or ""
            if v != (rw.get(key, {}).get(slot) or ""):
                cls, _, name = key.partition("·")
                row("戴", {"key": key, "slot": slot, "id": v}, cls, name, v, "", 0, pets.SLOT_ZH.get(slot, slot))
    lk, rk = local.get("装备", {}), led["装备"]
    for u in sorted(set(lk) | set(rk)):
        if canon(lk.get(u) or []) != canon(rk.get(u) or []):
            items = lk.get(u) or []
            row("装备", {"unit": u, "items": items}, "", "", "", "", 0,
                "、".join(f"{i.get('slot')}:{i.get('en')} {i.get('zh', '')}".strip() for i in items) or "撤下了")
    return out


def pet_sync(demo, d, names=None, say=True):
    """本机宠物记录 ⇄ 飞书「宠物账本」。飞书连不上就跳过，本机记录不受影响，下次再补。"""
    c = cfg()
    base = c.get("demo_base") if demo else c.get("base")
    if not base:
        return
    files = [d / f for f in PET_FILES.values()]
    try:
        # 本机还没有任何宠物记录、飞书上也还没有账本：没东西可记，也没东西可恢复，先不建表
        # （「看」会顺手开小卖部，不能一打开看板就往老师的 base 里建一张空表）
        tid = ledger_table(base, create=any(f.exists() for f in files))
        if not tid:
            return
        rows = pull_rows(base, tid)
        led = ledger_replay(rows)
        if not any(f.exists() for f in files):
            if any(led.values()):
                save_pet_state(d, led, *PET_FILES)
                n = len(led["换"])
                print(f"本机没有宠物记录，从飞书「{LEDGER}」恢复了：{n} 件换的配饰、{len(led['送'])} 件老师送的。")
            write_json(d / "同步.json", {"表": tid, "时间": time.strftime("%Y-%m-%d %H:%M"), "账本行数": len(rows)})
            return
        new = ledger_diff(pet_state(d), led, names or {})
        start = max([float(r.get("序号") or 0) for r in rows] + [0])
        for i, r in enumerate(new):
            r["序号"] = int(start) + i + 1
        for i in range(0, len(new), 200):
            lark("base", "+record-batch-create", "--base-token", base, "--table-id", tid,
                 "--json", json.dumps({"create_records": [{k: v for k, v in r.items() if v not in ("", None)}
                                                          for r in new[i:i + 200]]}, ensure_ascii=False))
        write_json(d / "同步.json", {"表": tid, "时间": time.strftime("%Y-%m-%d %H:%M"), "账本行数": len(rows) + len(new)})
        if say and new:
            print(f"宠物账本：往飞书补记了 {len(new)} 行。")
    except SystemExit as e:
        print(f"⚠️ 宠物账本这次没同步上（{e}）。本机记录没丢，下次「宠物」会再补。")


def item_names(pm):
    return {x["id"]: (x["en"], x["zh"]) for x in pm.get("shop", [])}


def cmd_pets(a):
    import pets
    d = pet_dir(a.demo)
    if a.action == "图片清单":
        out = HOME / "宠物" / "宠物图片清单.md"
        model = pull_all(a.demo)[0]
        out.write_text(pets.prompts_md(pets.compute(model, pet_state(d))), encoding="utf-8")
        print(f"图片清单：{out}\n生成好的 PNG 放进 {HOME / '宠物' / '图'}，文件名照清单写，下次「宠物」会自动换上。")
        return
    model, term = pull_all(a.demo)[0], pet_term()
    if a.action != "同步":
        pet_sync(a.demo, d, item_names(pets.compute(model, pet_state(d), term)), say=True)
    state = pet_state(d)
    today = time.strftime("%Y-%m-%d")
    if a.action == "同步":
        pet_sync(a.demo, d, item_names(pets.compute(model, state, term)))
        s = read_json(d / "同步.json", {})
        print(f"宠物账本对好了：飞书上一共 {s.get('账本行数', 0)} 行，最后一次同步 {s.get('时间', '')}。")
        return
    if a.action == "送":
        if len(a.args) < 2:
            sys.exit("用法：beike.py 宠物 送 <学生名字> <东西> [--班 高一3班] [--理由 …]\n能送的：" + "、".join(pets.GIFTS))
        name, item = a.args[0], a.args[1]
        if item not in pets.GIFTS:
            sys.exit(f"「{item}」不在能送的东西里。能送的：" + "、".join(pets.GIFTS))
        p = find_pet(pets.compute(model, state, term), name, a.cls)
        state["送"].append({"cls": p["cls"], "name": name, "item": item, "reason": a.reason or "", "date": today})
        save_pet_state(d, state, "送")
        pet_sync(a.demo, d, say=False)
        print(f"送好了：{p['cls']} {name} 拿到「{item}」，多 {pets.GIFT_BEANS} 颗豆子。下次打开宠物墙就能看到。")
        return
    if a.action in ("换", "退"):
        if len(a.args) < 2:
            sys.exit(f"用法：beike.py 宠物 {a.action} <学生名字> <配饰，中文或英文都行> [--班 高一3班]")
        pm = pets.compute(model, state, term)
        p, it = find_pet(pm, a.args[0], a.cls), find_item(pm, a.args[1])
        err = pets.buy(pm, state, p["key"], it["id"], today) if a.action == "换" else pets.refund(state, p["key"], it["id"])
        if err:
            sys.exit(err)
        save_pet_state(d, state, "换", "戴")
        left = pets.compute(model, state, term)
        pet_sync(a.demo, d, item_names(left), say=False)
        bal = next(x["balance"] for x in left["pets"] if x["key"] == p["key"])
        print(f"{'换好了' if a.action == '换' else '退好了'}：{p['cls']} {p['name']} 的{it['zh'] or it['en']}"
              f"（{it['price']} 颗）。现在还有 {bal} 颗豆子。")
        return
    if a.action == "装备":
        if len(a.args) < 2:
            sys.exit("用法：beike.py 宠物 装备 <单元，比如 Unit 3 或内容包> 头:binoculars:望远镜 手:map:地图 身边:tent:帐篷")
        key, specs = a.args[0], a.args[1:]
        unit = next((u for u in model["units"] if u["id"] == key or u["title"].lower().startswith(key.lower())), None)
        if not unit:
            sys.exit(f"找不到单元「{key}」。现在有：" + "、".join(u["title"] for u in model["units"]))
        items = []
        for sp in specs[:3]:
            parts = sp.split(":")
            if len(parts) < 2 or parts[0] not in pets.SLOTS:
                sys.exit(f"「{sp}」看不懂，要写成 头:英文:中文、手:英文:中文 或 身边:英文:中文。")
            items.append({"slot": parts[0], "en": parts[1], "zh": parts[2] if len(parts) > 2 else ""})
        state["装备"][unit["id"]] = items
        save_pet_state(d, state, "装备")
        pet_sync(a.demo, d, say=False)
        missing = [f"item-{pets.slug(x['en'])}.png" for x in items if not (pet_images() / f"item-{pets.slug(x['en'])}.png").exists()]
        print(f"{unit['title']} 的装备上架小卖部：" + "、".join(f"{x['en']} {x['zh']}（{x['slot']}）" for x in items))
        if missing:
            print("这几件还没有图（先用文字小牌子代替）：" + "、".join(missing) + "。跑「宠物 图片清单」拿到画图说明。")
        return
    if a.action == "开店":
        return pet_shop(a, model, d, term)
    if a.action == "导图":
        if not a.args:
            sys.exit("用法：beike.py 宠物 导图 <放着新图的文件夹>（文件名照「宠物 图片清单」写）")
        n = import_pet_images(Path(a.args[0]).expanduser(), pet_images(), overwrite=True)
        print(f"导进 {n} 张图到 {pet_images()}。下次「宠物」就用上了。")
        return
    if a.action:
        sys.exit(f"不认识「{a.action}」。可以：宠物、宠物 开店、宠物 换/退、宠物 送、宠物 装备、宠物 同步、宠物 图片清单、宠物 导图。")

    last = read_json(d / "上次.json", {})
    pm = pets.compute(model, state, term, last)
    imgs = pets.image_urls(pm, pet_images(), "../图/" if a.demo else "图/")
    page = d / "宠物墙.html"
    page.write_text(pets.render_html(pm, (HERE.parent / "assets" / "pets.html").read_text(encoding="utf-8"), imgs),
                    encoding="utf-8")
    os.chmod(page, 0o600)
    look = build_look(a.demo)[4]           # 宠物墙和成绩在同一页看板里，打开就停在「宠物」页签
    write_json(d / "上次.json", pets.snapshot(pm))
    print(f"看板（宠物页签）：{look}")
    print(f"单独的宠物墙（备用）：{page}")
    print(pets.change_text(pm))
    if not a.no_open and sys.platform == "darwin":
        subprocess.run(["open", look.as_uri() + "#宠物"])


def pet_shop(a, model, d, term):
    """课上开小卖部：本机起一个只有这台电脑能打开的网页（127.0.0.1 + 随机口令），
    学生上来点自己的宠物、挑配饰；豆子够才能换，写进 ~/.beike/宠物/换的.json。没人用 30 分钟自动关。"""
    import pets, secrets, threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    token = secrets.token_urlsafe(12)
    img_dir = pet_images()
    tpl = (HERE.parent / "assets" / "pets.html").read_text(encoding="utf-8")
    lock, seen = threading.Lock(), {"t": time.time()}
    today = time.strftime("%Y-%m-%d")
    board = HOME / "看板" / "看板.html"

    def pm_now():
        return pets.compute(model, pet_state(d), term)

    class H(BaseHTTPRequestHandler):
        def log_message(self, *x):
            pass

        def send(self, code, body, ctype="application/json; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def ok(self):
            seen["t"] = time.time()
            return self.path.split("?", 1)[0].startswith(f"/{token}/")

        def do_GET(self):
            if not self.ok():
                return self.send(404, b"not found", "text/plain")
            rest = self.path.split("?", 1)[0][len(token) + 2:]
            if rest == "board" and board.is_file():
                live = json.dumps(f"/{token}/")
                page = board.read_text(encoding="utf-8").replace(
                    "</head>", f"<script>window.PETS_LIVE = {live};</script>\n</head>", 1)
                return self.send(200, page.encode("utf-8"), "text/html; charset=utf-8")
            if rest in ("", "index.html"):
                pm = pm_now()
                html_ = pets.render_html(pm, tpl, pets.image_urls(pm, img_dir, "图/"), {"api": f"/{token}/api/"})
                return self.send(200, html_.encode("utf-8"), "text/html; charset=utf-8")
            from urllib.parse import unquote
            f = unquote(rest)
            if f.startswith("图/") and re.fullmatch(r"[a-z0-9-]+\.png", f[2:]) and (img_dir / f[2:]).is_file():
                return self.send(200, (img_dir / f[2:]).read_bytes(), "image/png")
            self.send(404, b"not found", "text/plain")

        def do_POST(self):
            if not self.ok():
                return self.send(404, b"not found", "text/plain")
            act = self.path.rsplit("/", 1)[-1]
            try:
                body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 4096)) or b"{}")
            except ValueError:
                body = {}
            with lock:
                state, pm = pet_state(d), pm_now()
                key, iid = str(body.get("key", "")), str(body.get("id", ""))
                if act == "buy":
                    err = pets.buy(pm, state, key, iid, today)
                elif act == "refund":
                    err = pets.refund(state, key, iid)
                elif act == "wear":
                    err = pets.wear(pm, state, key, str(body.get("slot", "")), iid)
                else:
                    err = "不认识。"
                if not err:
                    save_pet_state(d, state, "换", "戴")
                pm = pm_now()
            out = {"error": err, "pet": next((p for p in pm["pets"] if p["key"] == key), None), "scenes": pm["scenes"]}
            self.send(200, json.dumps(out, ensure_ascii=False).encode("utf-8"))

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    url = f"http://127.0.0.1:{srv.server_address[1]}/{token}/"
    if a.board:                          # 「看」在后台开的：地址交给「看」，之后的输出写进日志，不再占着它
        import signal
        print(f"小卖部开了：{url}", flush=True)
        sys.stdout = open(HOME / "看板" / "小卖部.log", "a", encoding="utf-8", buffering=1)
        signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
        print(f"\n{time.strftime('%Y-%m-%d %H:%M')} 跟看板一起开的小卖部")
    else:
        print(f"小卖部开了：{url}\n只有这台电脑能打开。学生点自己的宠物 → 小卖部 → 挑配饰。没人用 30 分钟自动关。")
        print(pets.change_text(pets.compute(model, pet_state(d), term, read_json(d / "上次.json", {}))))
    if not a.no_open and sys.platform == "darwin":
        subprocess.run(["open", url])

    def idle():
        while time.time() - seen["t"] < 30 * 60:
            time.sleep(20)
        srv.shutdown()
    threading.Thread(target=idle, daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    print("小卖部关了。")
    pet_sync(a.demo, d, item_names(pm_now()))


# ── 收尾 / 期末（算在 archive.py）──────────────────────
def word_rows(demo):
    """飞书「词表」表（有就拉）。收尾在这台电脑上找不到背课包时，词表从这里来。只读。"""
    c = cfg()
    base = c.get("demo_base") if demo else c.get("base")
    tables = {t["name"]: t["id"] for t in lark("base", "+table-list", "--base-token", base)["tables"]}
    return pull_rows(base, tables["词表"]) if "词表" in tables else []


def cat_home(demo):
    """演示数据的课目录单独放，不混进老师真的课目录（不然下次发会把假学生的期末课发出去）。"""
    return HOME / "演示" if demo else HOME


def cmd_wrap(a):
    import archive
    model, records, pulled, roster_from = pull_all(a.demo)
    cat, _ = archive.catalog(cat_home(a.demo))
    n, u, files = archive.wrap_up(HOME, model, cat, a.which, word_rows(a.demo), records,
                                  cat_home=cat_home(a.demo))
    print(f"第 {n} 课「{u['title']}」收尾好了（只读了飞书，没改任何东西）：")
    for p in files:
        print(f"  {p}")
    print("\n" + files[1].read_text(encoding="utf-8").strip())
    if a.kb:
        print(archive.upload_plan(files, a.kb, u["title"], model["meta"].get("demo")))
    else:
        print("\n要存进知识库的话，先问老师存到哪个知识库，再跑「beike.py 收尾 --上传 <知识库>」看会传哪几个文件。")


def cmd_final(a):
    import archive
    model, records, pulled, roster_from = pull_all(a.demo)
    entry, stats, cw, per, src, md, no_zh = archive.make_final(
        cat_home(a.demo), model, records, word_rows(a.demo), archive_home=HOME, trial=a.no_deploy)
    print(archive.final_text(stats, cw))
    print(f"\n课目录里多了一课「{entry.get('标题')}」（packId {entry['packId']}）。"
          + ("这是试做，只在「只生成」的网页里有。" if a.no_deploy else "下次「发」的时候它会跟着出现在学生页上，链接不变。"))
    print(f"全班最卡的词表（每个人的词在附录里，备查）：{md}")
    if no_zh:
        print("这几个词没找到中文，没放进网页：" + "、".join(no_zh))
    if src != "learning.py":
        print(f"（每人没拿下的词这次是按{src}算的。）")
    if model["meta"].get("demo"):
        print("（演示数据：课目录写在 " + str(cat_home(True) / "课") + "，不在老师真的课目录里。）")


def cmd_groups(a):
    save_cfg(groups=a.names)
    print("以后收作业只看这几个微信群：" + ("、".join(a.names) if a.names else "不限（所有聊天里搜结果码）"))


# ── 状态 ────────────────────────────────────────────
def cmd_status(a):
    c = cfg()
    print("名单：" + (summary(roster.read(ROSTER)) if ROSTER.exists() else "还没有"))
    print("成绩表：" + (c.get("base_url") or "还没有"))
    print("表单：" + (c.get("form") or "还没有（学生只能发结果码）"))
    print("学生链接：" + (c.get("link") or "还没发过"))
    print("班群：" + ("、".join(c.get("groups") or []) or "没指定（收作业时在所有微信聊天里搜结果码）"))
    print("wechat-cli：" + (find_wechat_cli() or "还没装"))
    if c.get("last"):
        print(f"链接现在打开是：{c['last']}（{c.get('last_at', '')} 发的）")
    import units, learning
    es = [e for e in units.lessons(HOME) if not e.get("试做")]
    if es:
        print(f"课目录：学生页上 {len(es)} 课，最新的是{units.label(es[-1])}「{es[-1].get('标题', '')}」")
    p = learning.load_plan(HOME)
    if p:
        print("复习：" + learning.plan_sentence(p))
    print("「我的复习」：" + ("点开现查（" + c["review_api"] + "）" if c.get("review_api") else "发的时候写进网页（没配 review_api）"))


def main():
    ap = argparse.ArgumentParser(description="背单词闯关：老师说一句话，这里跑一条")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("名单", help="存几个班的名单")
    p.add_argument("file", nargs="?")
    p.add_argument("--班", dest="cls", default="", help="这段名单没写班级时，算哪个班")
    p.set_defaults(fn=cmd_roster)

    p = sub.add_parser("建表", help="在飞书里建成绩表和交作业表单")
    p.add_argument("--重建", dest="force", action="store_true")
    p.set_defaults(fn=cmd_setup)

    p = sub.add_parser("表单", help="存飞书表单分享链接")
    p.add_argument("url")
    p.set_defaults(fn=cmd_form)

    p = sub.add_parser("发", help="生成网页并发布")
    p.add_argument("wordlist", help="词表 md")
    p.add_argument("--剧情", dest="episode")
    p.add_argument("--不带错题", dest="no_review", action="store_true")
    p.add_argument("--只生成", dest="no_deploy", action="store_true",
                   help="只生成网页不发布（试做时用）")
    p.set_defaults(fn=cmd_send)

    p = sub.add_parser("收", help="收作业：抓微信群里的结果码写进成绩表，再从表里报")
    p.add_argument("file", nargs="?", help="可选：手动粘进来的结果码")
    p.add_argument("--全部", dest="all", action="store_true", help="不只看最近一单元")
    p.add_argument("--从", dest="since", help="从哪天开始搜群，默认上次发的那天")
    p.add_argument("--不抓微信", dest="no_wechat", action="store_true")
    p.set_defaults(fn=cmd_collect)

    p = sub.add_parser("课", help="课目录：列表 / 撤 <第几课> / 恢复 <第几课> / 改名 <第几课> <新名字>")
    p.add_argument("action", nargs="?", default="列表")
    p.add_argument("args", nargs="*")
    p.add_argument("--只生成", dest="no_deploy", action="store_true", help="只生成网页，学生链接不动")
    p.set_defaults(fn=cmd_units)

    p = sub.add_parser("复习", help="全班层面的复习设置：看 / 去掉 <词…> / 加上 <词…> / 关掉（不用确认）")
    p.add_argument("action", nargs="?", default="看")
    p.add_argument("words", nargs="*")
    p.set_defaults(fn=cmd_review)

    p = sub.add_parser("看", help="看板：从飞书拉成绩、名单、单元、词表，生成本地网页并打开")
    p.add_argument("--摘要", dest="summary_only", action="store_true",
                   help="只打印一段能发微信的文字，不打开网页（每天定时推送用）")
    p.add_argument("--不打开", dest="no_open", action="store_true")
    p.add_argument("--演示", dest="demo", action="store_true", help="用假数据那张表")
    p.add_argument("--宠物", dest="pets", action="store_true", help="打开时直接到「宠物」页签")
    p.add_argument("--不开店", dest="no_shop", action="store_true", help="不顺手开小卖部（--摘要 本来就不开）")
    p.set_defaults(fn=cmd_look)

    p = sub.add_parser("宠物", help="宠物墙：用成绩算每个学生的宠物，生成本地网页（可投屏）")
    p.add_argument("action", nargs="?", default="", help="空 / 开店 / 换 / 退 / 送 / 装备 / 同步 / 图片清单 / 导图")
    p.add_argument("args", nargs="*")
    p.add_argument("--班", dest="cls")
    p.add_argument("--理由", dest="reason")
    p.add_argument("--不打开", dest="no_open", action="store_true")
    p.add_argument("--演示", dest="demo", action="store_true", help="用假数据表（config 里的 demo_base）")
    p.add_argument("--跟看板", dest="board", action="store_true", help=argparse.SUPPRESS)
    p.set_defaults(fn=cmd_pets)

    p = sub.add_parser("收尾", help="一课结束：写存档和学情摘要到 ~/.beike/存档/<packId>/（只读飞书）")
    p.add_argument("which", nargs="?", help="第几课（数字），不写就是最近一课；也认 packId、标题开头")
    p.add_argument("--上传", dest="kb", metavar="知识库", help="只列出准备上传哪几个文件到哪个知识库，不真上传")
    p.add_argument("--演示", dest="demo", action="store_true", help="用假数据表（config 里的 demo_base）")
    p.set_defaults(fn=cmd_wrap)

    p = sub.add_parser("期末", help="期末复习包：全班一直没拿下的词 + 每人自己没拿下的词 → 课目录里多一课")
    p.add_argument("--只生成", dest="no_deploy", action="store_true", help="试做：只在「只生成」的网页里出现")
    p.add_argument("--演示", dest="demo", action="store_true", help="用假数据表（config 里的 demo_base）")
    p.set_defaults(fn=cmd_final)

    p = sub.add_parser("群", help="记住三个班群的名字，收作业只在这几个群里搜")
    p.add_argument("names", nargs="*")
    p.set_defaults(fn=cmd_groups)

    p = sub.add_parser("状态", help="看现在记着什么")
    p.set_defaults(fn=cmd_status)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
