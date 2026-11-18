# -*- coding: utf-8 -*-
"""收尾和期末。beike.py 收尾 / 期末 把飞书拉下来的东西交给这里；这里不连网、不碰凭证、不写飞书。

    收尾：~/.beike/存档/<packId>/存档.md + 学情摘要.md（演示数据放 ~/.beike/存档/演示/<packId>/）
    上传：只列出「哪个文件 → 哪个知识库」，不上传。老师点头后由 WorkBuddy 用自己的 ima 知识库工具传。
    期末：全班一直没拿下的词 + 每个人自己没拿下的词 → 一课「期末复习」，加进课目录。

数从哪来，不自己另算一套：
- 每班交了几个、四个数、易错词榜、谁没交、要老师看的人、复习回来没有 → dashboard.compute 的看板模型
- 课目录 → units.py；每个学生每个词的状态 → learning.py。
  learning.py 还没有（或接不上）时，用本文件里的 _stub_learning 顶上，规则按《下一版需求》第 3 节；输出里会说用的是桩。

开发时不用连飞书也能跑：
    python3 archive.py --fake ../../看板假数据/fake.json --home /tmp/x 收尾 [第几课] [--上传 知识库]
    python3 archive.py --fake ../../看板假数据/fake.json --home /tmp/x 期末
"""
import json, os, re, sys, time
from collections import OrderedDict, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dashboard  # noqa: E402

STATES = dashboard.STATES
WORD_RE = dashboard.WORD_RE
split_list = dashboard.split_list
num = dashboard.num


# ── 课目录（units.py 没写好之前的桩）────────────────────────
def _stub_catalog(home):
    """读 ~/.beike/课/目录.json。格式按第 0 节：每一课 标题、packId、词表、背课包、发布时间、第几课。"""
    try:
        d = json.loads((Path(home) / "课" / "目录.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = (d.get("课") or d.get("lessons") or d.get("units") or []) if isinstance(d, dict) else d
    out = []
    for i, r in enumerate(rows, 1):
        pid = r.get("packId") or r.get("内容包")
        if not pid:
            continue
        out.append({"n": num(r.get("n") or r.get("第几课"), i) or i, "packId": pid,
                    "title": r.get("title") or r.get("标题") or pid,
                    "date": str(r.get("published_at") or r.get("发布时间") or "")[:10],
                    "hidden": bool(r.get("hidden") or r.get("撤")), "kind": r.get("kind") or ""})
    return out


def _units():
    try:
        import units  # beike-loop 写的
        return units
    except ImportError:
        return None


def catalog(home):
    """[{n, packId, title, date, hidden, kind}]，按第几课排。撤掉的课也在（收尾照样能做）。"""
    U = _units()
    if not U:
        return _stub_catalog(home), "桩"
    out = [{"n": num(e.get("第几课")), "packId": e["packId"], "title": e.get("标题") or e["packId"],
            "date": str(e.get("发布时间") or "")[:10], "hidden": bool(e.get("撤了")), "kind": e.get("类型") or "课"}
           for e in U.lessons(home, 含撤了=True)]
    return out, "units.py"


def lesson_files(home, pid):
    U = _units()
    if U:
        d = U._dir(home) / U._safe(pid)
        return U.pack(pid, home), (d / "词表.md") if (d / "词表.md").exists() else None
    d = Path(home) / "课" / pid
    pack = None
    try:
        pack = json.loads((d / "pack.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    return pack, (d / "词表.md") if (d / "词表.md").exists() else None


def vocab_of(pid, pack, word_rows):
    """这一课的词：有背课包用背课包，没有就用飞书「词表」表。"""
    if pack:
        items = pack.get("items") or {}
        its = items.values() if isinstance(items, dict) else items
        out = [{"w": x.get("en", ""), "zh": x.get("zh", ""), "src": "本课"} for x in its if x.get("type") == "word"]
        if out:
            return out
    return [{"w": str(r.get("词") or "").strip(), "zh": str(r.get("中文") or ""), "src": str(r.get("来源") or "本课")}
            for r in word_rows if str(r.get("内容包") or "").strip() == pid and r.get("词")]


# ── 每个学生每个词的状态（learning.py 没写好之前的桩）────────
def _stub_learning(records, order, vocab_by_pack):
    """第 3 节的规则（和 learning.py 约定的一样）：
    - 每个人每一课只看第一次交的那份；「用时偏短」的不算，往后顺延到下一份；
    - 某个词「还不会」或「差一点」→ 进这个学生自己的复习单；
    - 以后哪一课里这个词出现且第一次就对 → 连续对 +1；连续两次对 → 拿下；错一次重新数。
    返回 {(班级, 姓名): {词: {"状态", "错在哪几课", "连续对几次"}}}"""
    rank = {pid: i for i, pid in enumerate(order)}

    def k(r):
        pid = str(r.get("内容包") or "")
        return (rank.get(pid, len(rank) if pid.startswith("review-") else -1), pid, num(r.get("第几次"), 1))
    state, seen = defaultdict(dict), set()
    for r in sorted(records, key=k):
        if str(r.get("用时偏短", "")).strip() == "是":
            continue
        key = (str(r.get("班级", "")).strip(), str(r.get("姓名", "")).strip())
        pid = str(r.get("内容包") or "")
        if (key, pid) in seen:
            continue
        seen.add((key, pid))
        nope = [w for w in split_list(r.get("还不会清单")) if WORD_RE.fullmatch(w)]
        shaky = [w for w in split_list(r.get("差一点清单")) if WORD_RE.fullmatch(w) and w not in nope]
        wrong = set(nope) | set(shaky)
        tested = {v["w"] for v in vocab_by_pack.get(pid, [])} | wrong
        mine = state[key]
        for w in tested:
            s = mine.get(w)
            if w in wrong:
                if not s:
                    s = mine[w] = {"状态": "", "错在哪几课": [], "连续对几次": 0}
                s["状态"], s["连续对几次"] = ("还不会" if w in nope else "差一点"), 0
                if pid not in s["错在哪几课"]:
                    s["错在哪几课"].append(pid)
            elif s and s["状态"] != "拿下":
                s["连续对几次"] += 1
                if s["连续对几次"] >= 2:
                    s["状态"] = "拿下"
    return state


def word_states(records, order, vocab_by_pack, home=None):
    """{(班级, 姓名): {词: {"状态": 还不会/差一点/拿下, "错在哪几课", "连续对几次"}}}。
    learning.py 有就用它（beike-loop 写的，接口见共享笔记「课目录与learning-接口.md」），接不上就用桩并说明。"""
    try:
        import learning
    except ImportError:
        return _stub_learning(records, order, vocab_by_pack), "桩"
    try:
        res = learning.compute(records, home=home, vocab={pid: [v["w"] for v in vs] for pid, vs in vocab_by_pack.items()})
        out = {}
        for key, words in res["学生"].items():
            out[tuple(key.split("·", 1)) if isinstance(key, str) else tuple(key)] = words
        return out, "learning.py"
    except (AttributeError, TypeError, KeyError, ValueError) as e:
        return _stub_learning(records, order, vocab_by_pack), f"桩（learning.py 接不上：{e}）"


# ── 选哪一课 ────────────────────────────────────────────
def pick(model, cat, which):
    """which：空 = 最近一课；数字 = 第几课；也认 packId 和标题开头。返回 (第几课, 看板里的这一课)。"""
    units = model["units"]
    if not units:
        sys.exit("成绩表里还没有任何一课的提交，没东西可以收尾。")
    by_id = {u["id"]: u for u in units}
    numbered = [(c["n"], c["packId"]) for c in cat if c["packId"] in by_id]
    if {p for _, p in numbered} != set(by_id):   # 课目录没把每一课都记上（比如假数据表的课）：按看板顺序数
        numbered = [(i, u["id"]) for i, u in enumerate(units, 1)]
    if not which:
        n, pid = numbered[-1]
        return n, by_id[pid]
    w = str(which).strip()
    m = re.fullmatch(r"第?\s*(\d+)\s*课?", w)
    if m:
        hit = [x for x in numbered if x[0] == int(m.group(1))]
        if hit:
            return hit[0][0], by_id[hit[0][1]]
    for n, pid in numbered:
        if pid == w or by_id[pid]["title"].lower().startswith(w.lower()):
            return n, by_id[pid]
    sys.exit(f"找不到「{w}」这一课。现在有：" + "；".join(f"第{n}课 {by_id[p]['title']}" for n, p in numbered))


def only_lessons(model):
    """看板模型里只留正课。期末/复习分页也会进看板（课目录里有），但它们不是「一课」：
    不参与收尾编号、上一课对比、期末算词。"""
    return dict(model, units=[u for u in model["units"] if (u.get("kind") or "课") == "课"])


def archive_dir(home, pid, demo):
    d = Path(home) / "存档" / ("演示" if demo else "") / pid
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── 几个公共小算式 ──────────────────────────────────────
def _known(u):
    return [s for s in u["students"] if not s.get("unknown")]


def class_rows(u):
    """每班：人数、交了几个、四个数的平均（交了的人，看最近一次）、对题率。"""
    out = []
    for c in u["classes"]:
        ss = [s for s in _known(u) if s["cls"] == c["cls"] and s["done"]]
        avg = [round(sum(s["counts"][i] for s in ss) / len(ss), 1) if ss else None for i in range(4)]
        out.append({"cls": c["cls"], "total": c["total"], "done": c["done"], "missing": c["missing"],
                    "avg": avg, "right": u["class_right"].get(c["cls"])})
    return out


def hard_words(u, k=5):
    return [a for a in u["wrong"] if a["is_word"]][:k]


def _prev_unit(model, u):
    """看板里的上一课；第一课返回 None。"""
    ids = [x["id"] for x in model["units"]]
    i = ids.index(u["id"])
    return model["units"][i - 1] if i else None


def two_in_a_row_missing(model, u):
    """这一课和上一课都没交的人（按看板里的课的顺序）。只进存档附录，不进摘要。"""
    prev = _prev_unit(model, u)
    if prev is None:
        return None
    out = []
    for c in u["classes"]:
        pm = set(next(x for x in prev["classes"] if x["cls"] == c["cls"])["missing"])
        out += [(c["cls"], n) for n in c["missing"] if n in pm]
    return prev, out


def attention_known(u):
    ok = {(s["cls"], s["name"]) for s in _known(u)}
    return [a for a in u["attention"] if (a["cls"], a["name"]) in ok]


def _f(x):
    return "—" if x is None else (f"{x:g}" if isinstance(x, float) else str(x))


# ── 存档.md ─────────────────────────────────────────────
def item_line(it):
    t = it.get("type")
    if t == "word":
        return f"{it.get('zh', '')} → {it.get('en', '')}"
    if t == "cloze":
        return f"{it.get('context', '')}（答案 {it.get('answer', '')}）"
    if t == "compose":
        return f"{it.get('prompt', '')}（必用 {'、'.join(it.get('must') or [])}）"
    if t == "fix":
        return f"{it.get('wrong', '')} → {it.get('answer', '')}（{it.get('reason', '')}）"
    if t == "sentence":
        return f"{it.get('zh', '')} → {it.get('answer', '')}"
    return json.dumps(it, ensure_ascii=False)[:120]


def archive_md(model, n, u, vocab, pack, meta, states=None):
    demo = model["meta"].get("demo")
    L = [f"# 存档：第 {n} 课 {u['title']}", ""]
    if demo:
        L += ["> 演示数据，不是真学生。", ""]
    L += [f"- 内容包：{u['id']}", f"- 发布：{u['date'] or '不知道'}", f"- 题数：{u['n'] or '不知道'}",
          f"- 收尾时间：{meta['when']}", f"- 数据：{model['meta'].get('base_name', '成绩表')}，"
          f"{u['submissions']} 条提交（{u['repeaters']} 人做了不止一次）。只读，没改飞书。", ""]

    L += ["## 词表", ""]
    if vocab:
        L += ["| 词 | 中文 | 来源 |", "|---|---|---|"] + [f"| {v['w']} | {v['zh']} | {v['src']} |" for v in vocab]
    else:
        L.append("这一课的词表没找到（背课包和飞书「词表」表里都没有）。")
    L.append("")

    L += ["## 题", ""]
    if pack:
        items = pack.get("items") or {}
        for lv in pack.get("levels") or []:
            L.append(f"### {lv.get('title', lv.get('id', ''))}")
            for iid in lv.get("items") or []:
                it = items.get(iid) if isinstance(items, dict) else None
                if it:
                    L.append(f"- {iid}　{item_line(it)}")
            L.append("")
    else:
        L += [f"这台电脑上没有这一课的背课包（~/.beike/课/{u['id']}/pack.json），只记题数 {u['n'] or '不知道'}。", ""]

    L += ["## 全班结果", "", "四个数是交了的人最近一次的平均；对题率 = 对了 ÷（总题数 − 待老师看）。", "",
          "| 班级 | 人数 | 交了 | 没交 | 对了 | 差一点 | 还不会 | 待老师看 | 对题率 |", "|---|---|---|---|---|---|---|---|---|"]
    for r in class_rows(u):
        L.append(f"| {r['cls']} | {r['total']} | {r['done']} | {len(r['missing'])} | "
                 + " | ".join(_f(x) for x in r["avg"]) + f" | {_f(r['right'])}{'%' if r['right'] is not None else ''} |")
    if u["mismatch"]:
        L.append(f"\n四个数加起来不等于题数的提交 {len(u['mismatch'])} 条：{'、'.join(u['mismatch'][:10])}")
    if u["unknown"]:
        L.append(f"\n另有 {len(u['unknown'])} 条提交的名字不在名单里，没算进上面（名字见看板）。")
    L.append("")

    L += ["## 易错词榜（每人只看第一次提交）", "", "| 排名 | 词 / 题 | 中文 | 还不会 | 差一点 | 合计 | "
          + " | ".join(model["classes"]) + " |", "|---|---|---|---|---|---|" + "---|" * len(model["classes"])]
    for i, a in enumerate(u["wrong"][:20], 1):
        L.append(f"| {i} | {a['item']} | {a['zh']} | {a['nope']} | {a['shaky']} | {a['people']} | "
                 + " | ".join(str(a["by"].get(c, 0)) for c in model["classes"]) + " |")
    L.append("")

    rec = [r for r in model["recovery"] if r["to_id"] == u["id"]]
    if rec:
        L += ["## 上一课的错词，这一课复习回来了没有", "", "| 词 | 中文 | 原来错的人 | 这次第一次就对 | 还错 | 这次没交 |", "|---|---|---|---|---|---|"]
        L += [f"| {r['word']} | {r['zh']} | {r['before']} | {r['got']} | {len(r['still'])} | {r['skip']} |" for r in rec]
        L.append("")

    # ── 附录：每个人的情况，备查。不进学情摘要，不推给老师。
    L += ["---", "", "# 附录：每个人的情况（备查）", "",
          "上面只讲全班。这里是系统替老师盯着的每个人，想查某个人时再看。", ""]
    L += ["## 谁没交", ""]
    for r in class_rows(u):
        L.append(f"- {r['cls']}（{len(r['missing'])} 人）：" + ("、".join(r["missing"]) if r["missing"] else "全交了"))
    L.append("")

    two = two_in_a_row_missing(model, u)
    if two is not None:
        prev, who = two
        L += [f"## 这一课和上一课（{prev['title']}）都没交", ""]
        L += [f"- {c} {n}" for c, n in who] or ["没有。"]
        L.append("")

    L += ["## 系统标出来要多留意的人", ""]
    att = attention_known(u)
    L += [f"- {a['cls']} {a['name']}：{'，'.join(a['why'])}" for a in att] or ["没有。"]
    L.append("")

    if states:
        L += ["## 每个人还没拿下的词（系统自动排进他自己的复习）", ""]
        for (c, nm), ws in sorted(states.items()):
            mine = sorted(w for w, s in ws.items() if s["状态"] != "拿下")
            if mine:
                L.append(f"- {c} {nm}（{len(mine)}）：" + "、".join(mine))
        L.append("")
    return "\n".join(L)


# ── 学情摘要.md（一页以内，给备课时问 AI 用）──────────────────
def summary_md(model, n, u, states=None):
    demo = model["meta"].get("demo")
    rows = class_rows(u)
    total, done = sum(r["total"] for r in rows), sum(r["done"] for r in rows)
    L = [f"# 学情摘要：第 {n} 课 {u['title']}", ""]
    if demo:
        L += ["这是演示数据，不是真学生。", ""]
    L.append(f"这一课{('在 ' + u['date'] + ' 发出') if u['date'] else ''}，一共 {u['n'] or '若干'} 道题。"
             f"{len(rows)} 个班共 {total} 人，交了 {done} 人。"
             + "；".join(f"{r['cls']}交了 {r['done']}/{r['total']}" for r in rows) + "。")
    if u.get("avg_right") is not None:
        L.append(f"整体对了多少：交了的人平均对 {u['avg_right']}% 的题（对了 ÷（题数 − 待老师看的造句），看最近一次提交）。")
    if u.get("compose"):
        L.append(f"有 {u['compose']} 人的造句等老师看，在看板里。")
    L.append("")

    prev = _prev_unit(model, u)
    if prev is None:
        L.append("这是第一课，还没法和上一课比。")
    else:
        prow = class_rows(prev)
        pt, pd = sum(r["total"] for r in prow), sum(r["done"] for r in prow)
        rate, prate = round(100 * done / max(1, total)), round(100 * pd / max(1, pt))

        def _cmp(now, before, big):
            d = now - before
            return "多了不少" if d >= big else "少了不少" if d <= -big else "多了一点" if d >= 3 else "少了一点" if d <= -3 else "差不多"
        bits = [f"交作业率 {prate}% → {rate}%（{_cmp(rate, prate, 10)}）"]
        ar, par = u.get("avg_right"), prev.get("avg_right")
        if ar is not None and par is not None:
            c = _cmp(ar, par, 8).replace("多了", "高了").replace("少了", "低了")
            bits.append(f"交了的人平均对题率 {par}% → {ar}%（{c}）")
        L.append(f"和上一课（{prev['title']}）比：{'；'.join(bits)}。")
    L.append("")

    hw = hard_words(u)
    if hw:
        L.append(f"全班最难的 {len(hw)} 个词（每人只看第一次提交）是："
                 + "；".join(f"{a['item']}{('（' + a['zh'] + '）') if a['zh'] else ''}，还不会 {a['nope']} 人、差一点 {a['shaky']} 人"
                            for a in hw) + "。")
    else:
        L.append("这一课还没有人错词。")
    other = [a for a in u["wrong"] if not a["is_word"]][:2]
    if other:
        L.append("词以外错得多的题：" + "；".join(f"{a['item']}（{a['people']} 人）" for a in other) + "。")
    L.append("")

    rated = [r for r in rows if r["right"] is not None and r["done"]]
    if len(rated) >= 2:
        w = min(rated, key=lambda r: (r["right"], r["done"] / max(1, r["total"])))
        rest = [r for r in rated if r is not w]
        L.append(f"最弱的是{w['cls']}：交了的人平均对 {w['right']}% 的题，交作业率 {round(100 * w['done'] / max(1, w['total']))}%。"
                 + "其他班：" + "，".join(f"{r['cls']}对 {r['right']}%、交了 {round(100 * r['done'] / max(1, r['total']))}%" for r in rest) + "。")
        L.append("")

    if states:
        queued = sum(1 for ws in states.values() if any(s["状态"] != "拿下" for s in ws.values()))
        pend = sum(1 for ws in states.values() for s in ws.values() if s["状态"] != "拿下")
        got = sum(1 for ws in states.values() for s in ws.values() if s["状态"] == "拿下")
        L.append(f"系统给 {queued} 人排了复习（每人只复习自己没拿下的词），一共 {pend} 个（人 × 词）还没拿下。"
                 f"到这一课为止，个人复习单里已经拿下（连续两次第一次就对）{got} 个。")
        L.append("")

    rec = [r for r in model["recovery"] if r["to_id"] == u["id"]]
    if rec:
        before = sum(r["before"] - r["skip"] for r in rec)
        got = sum(r["got"] for r in rec)
        L.append(f"复习回来了多少：这一课复习了上一课错的 {len(rec)} 个词，原来错过、这次也交了的 {before} 人次里，"
                 f"{got} 人次第一次就对了（{round(100 * got / max(1, before))}%）。"
                 + "；".join(f"{r['word']} {r['got']}/{r['before'] - r['skip']}" for r in rec) + "。")
    else:
        L.append("复习回来了多少：这一课没有排上一课的错词复习，说不了。")
    L += ["", f"（背单词闯关自动生成，{time.strftime('%Y-%m-%d')}。数字来自成绩表，只讲全班整体；"
              "每个人的情况在同一文件夹的 存档.md 附录里。）"]
    return "\n".join(L)


def wrap_up(home, model, cat, which, vocab_rows, records, cat_home=None):
    """写存档到 home/存档/。cat_home = 课目录在哪（演示数据用单独的目录），默认同 home。返回 (第几课, 这一课, [文件])。"""
    model = only_lessons(model)
    n, u = pick(model, cat, which)
    cat_home = cat_home or home
    pack, _ = lesson_files(cat_home, u["id"])
    vocab = vocab_of(u["id"], pack, vocab_rows)
    order = [x["id"] for x in model["units"]]
    upto = order[:order.index(u["id"]) + 1]
    vb = {pid: vocab_of(pid, lesson_files(cat_home, pid)[0], vocab_rows) for pid in upto}
    recs = [r for r in records if str(r.get("内容包") or "") in set(upto) or str(r.get("内容包") or "").startswith("review-")]
    states, _src = word_states(recs, upto, vb, home=cat_home)
    d = archive_dir(home, u["id"], model["meta"].get("demo"))
    meta = {"when": time.strftime("%Y-%m-%d %H:%M")}
    files = []
    for name, text in (("存档.md", archive_md(model, n, u, vocab, pack, meta, states)),
                       ("学情摘要.md", summary_md(model, n, u, states))):
        p = d / name
        p.write_text(text + "\n", encoding="utf-8")
        os.chmod(p, 0o600)               # 有学生名字，只给本人读
        files.append(p)
    return n, u, files


def upload_plan(files, kb, title, demo):
    """只列出准备上传什么，不上传。"""
    L = ["", f"准备上传到知识库「{kb}」（这次没有上传，只是列出来）："]
    for p in files:
        L.append(f"  {p.name} → 「{kb}」/背单词闯关学情/{title}/{p.name}　（本机：{p}）")
    if demo:
        L.append("这是演示数据，不要传进老师的知识库。")
    else:
        L.append(f"先问老师：「把这一课的存档和学情摘要存进『{kb}』可以吗？」她点头以后，"
                 "用 WorkBuddy 自带的 ima 知识库工具传这两个文件（Markdown，原样上传）。")
    return "\n".join(L)


# ── 期末复习 ─────────────────────────────────────────────
def final_review(model, states, vocab_by_pack, class_k=20):
    """全班：所有课里一直没拿下的词，按还没拿下的人数排；每个人：自己复习单里还没拿下的词。"""
    roster_keys = {(s["cls"], s["name"]) for u in model["units"] for s in _known(u)}
    zh = {}
    for vs in vocab_by_pack.values():
        for v in vs:
            if v["zh"] and v["w"].lower() not in zh:
                zh[v["w"].lower()] = v["zh"]
    for u in model["units"]:
        for a in u["wrong"]:
            if a["zh"]:
                zh.setdefault(a["item"].lower(), a["zh"])
    per, cnt = OrderedDict(), defaultdict(int)
    for cls in model["classes"]:
        names = list(OrderedDict.fromkeys(s["name"] for u in model["units"] for s in _known(u) if s["cls"] == cls))
        for name in names:
            ws = states.get((cls, name), {})
            mine = sorted((w for w, s in ws.items() if s["状态"] != "拿下"),
                          key=lambda w: (-len(ws[w]["错在哪几课"]), w))
            if mine:
                per[(cls, name)] = [{"w": w, "zh": zh.get(w.lower(), "")} for w in mine]
            for w in mine:
                cnt[w] += 1
    class_words = [{"w": w, "zh": zh.get(w.lower(), ""), "people": c}
                   for w, c in sorted(cnt.items(), key=lambda x: (-x[1], x[0]))][:class_k]
    stats = {"words": len(cnt), "class_words": len(class_words), "students": len(per),
             "roster": len(roster_keys),
             "avg": round(sum(len(v) for v in per.values()) / max(1, len(roster_keys)), 1)}
    return class_words, per, stats


def final_text(stats, class_words):
    if not class_words:
        return "所有课的词大家都拿下了，没有要期末复习的词。"
    # 只讲全班整体，不点名（总原则：系统盯每个人，老师只看全班）。
    return (f"期末复习包一共 {stats['words']} 个词（所有课里还有人没拿下的）。"
            f"\n{stats['students']} 人有自己的期末复习，名单上平均每人 {stats['avg']} 个；学生页上每人只看到自己的词。"
            f"\n全班最卡的词（课上一起讲）：" + "、".join(f"{x['w']}（{x['people']} 人没拿下）" for x in class_words[:8])
            + (f" 等 {len(class_words)} 个" if len(class_words) > 8 else "") + "。")


def make_final(home, model, records, vocab_rows, archive_home=None, trial=False):
    """算期末复习，加进课目录（units.add_word_pack，类型「期末」），再在存档里留一份给老师看的清单。
    home = 课目录在哪（演示数据用单独的目录，别混进真目录）。返回 (条目, 统计, 全班词, 每人, 词状态来源, 清单文件)。"""
    U = _units()
    if not U:
        sys.exit("课目录（units.py）还没装上，期末复习没地方放。")
    model = only_lessons(model)
    order = [u["id"] for u in model["units"]]
    vb = {pid: vocab_of(pid, lesson_files(home, pid)[0], vocab_rows) for pid in order}
    states, src = word_states(records, order, vb, home=home)
    class_words, per, stats = final_review(model, states, vb)
    zh = {x["w"]: x["zh"] for x in class_words}
    for ws in per.values():
        zh.update({x["w"]: x["zh"] for x in ws})
    no_zh = sorted(w for w, z in zh.items() if not z)
    words = {w: z for w, z in zh.items() if z}
    pid = f"final-{time.strftime('%Y%m%d')}"
    # 学生页上每个人只看到自己没拿下的词（第 4 节验收：林小雨的期末分页里只有她自己的词）。
    # 全班词不另外塞给每个人：全班词里她没拿下的，本来就在她自己的单子里；全班词表给老师课上讲。
    entry = U.add_word_pack(pid, "期末复习", words, (),
                            {f"{c}·{n}": [x["w"] for x in ws] for (c, n), ws in per.items()},
                            类型="期末", 说明="这些是你前几课还没拿下的词，期末前再过一遍。", 试做=trial, home=home)
    d = archive_dir(archive_home or home, pid, model["meta"].get("demo"))
    L = [f"# 期末复习（{time.strftime('%Y-%m-%d')}）", "", final_text(stats, class_words), "",
         "## 全班最多人没拿下的词（课上一起讲）", "", "| 词 | 中文 | 还没拿下的人数 |", "|---|---|---|"]
    L += [f"| {x['w']} | {x['zh']} | {x['people']} |" for x in class_words]
    if no_zh:
        L += ["", "没找到中文、没放进网页的词：" + "、".join(no_zh)]
    L += ["", "---", "", "# 附录：每个人自己的词（备查，系统已经放进各人的期末分页）", ""]
    L += [f"- {c} {n}（{len(ws)}）：" + "、".join(x["w"] for x in ws) for (c, n), ws in per.items()]
    p = d / "期末复习.md"
    p.write_text("\n".join(L) + "\n", encoding="utf-8")
    os.chmod(p, 0o600)
    return entry, stats, class_words, per, src, p, no_zh


# ── 不连飞书，直接用 fake.json 跑 ──────────────────────────
def _fake(path):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    rs = OrderedDict()
    for s in d["students"]:
        rs.setdefault(s["班级"], []).append(s["姓名"])
    model = dashboard.compute(d["records"], rs, d["units"], d["words"],
                              meta={"base_name": "背单词闯关·假数据演示（本地 fake.json）", "demo": True})
    return model, d["records"], d["words"]


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="开发用：拿 fake.json 跑收尾 / 期末，不连飞书")
    ap.add_argument("--fake", required=True)
    ap.add_argument("--home", required=True)
    ap.add_argument("cmd", choices=["收尾", "期末"])
    ap.add_argument("which", nargs="?")
    ap.add_argument("--上传", dest="kb")
    a = ap.parse_args()
    model, records, words = _fake(a.fake)
    cat, src = catalog(a.home)
    if a.cmd == "收尾":
        n, u, files = wrap_up(a.home, model, cat, a.which, words, records)
        print(f"第 {n} 课 {u['title']} 存好了：" + "、".join(str(p) for p in files))
        if a.kb:
            print(upload_plan(files, a.kb, u["title"], True))
    else:
        entry, stats, cw, per, ssrc, p, _ = make_final(a.home, model, records, words)
        print(final_text(stats, cw))
        print(f"课目录里加了：{entry.get('标题')}（第 {entry.get('第几课')} 个分页，packId {entry['packId']}）；清单 {p}")
        print(f"（课目录：{src}；词状态：{ssrc}）")
