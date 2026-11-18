# -*- coding: utf-8 -*-
"""学情：每个学生哪些词还没拿下、全班哪几个词最该复习。每次从成绩表 + 课目录现算，不另存一份。

规则（《下一版需求》第 3 节）：
- 每个人每一课只看第一次交的那份。「用时偏短」的那份不算（多半是点着玩的），往后顺延到下一次。
- 一个词在那份里「第一遍作答」就对，记一次对；第一遍错了、后来改对的，算错。
  明细里写成「题号:第一遍>最后」，这里只看 > 前面那个。
- 错一次（还不会或差一点）→ 进这个人的复习单，连续对几次归零，记下错在哪一课。
- 在复习单里的词，以后哪一课（包括「我的复习」）第一遍就对 → 连续对 +1；连续两次 → 拿下，从单子里消失。
  拿下以后又错了，重新进单子。
- 全班最卡的词（只给老师课上讲，不进学生网页）= 这一课每个人第一次交的那份里（用时偏短的也算，和看板一样），
  还不会算 2 分、差一点算 1 分，排前 10 的词。和看板「全班最没拿下的词」同一个算法，
  只多一步：完形里的变形（devoted）并回原词（devote）。

    learning.compute(records, home=None, vocab=None, pack=None, zh=None)
      → {"学生": {"高一3班·林小雨": {"physician": {"状态": "还不会"|"差一点"|"拿下",
                                                 "错在哪几课": [packId…], "连续对几次": 0}}},
         "全班": [{"词": "devote", "人数": 12, "还不会": 8, "差一点": 4}, …前 10],
         "这一课": packId, "中文": {"physician": "内科医生", …}}
    learning.review_lists(model)        → {学生键: [还没拿下的词…]}
    learning.draft_plan(model, 来自, home) → 写 ~/.beike/复习计划.json，返回给老师的一两句话
    learning.load_settings / save_settings  → ~/.beike/复习设置.json（学期级：去掉 / 加上 / 下次关掉）

命令行（自己核对用）：python3 learning.py 成绩.json|结果码.txt [--home 目录] [--谁 高一3班·林小雨]
"""
import json, re, sys, time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import units  # noqa: E402
from dashboard import WORD_RE  # noqa: E402  「是不是一个词」只有 dashboard 里一份

RIGHT, SHAKY, WRONG = "对", "差一点", "还不会"
_RES = {"pass": RIGHT, "ok": RIGHT, "near": SHAKY, "fail": WRONG, "no": WRONG, "-": WRONG}
_RANK = {RIGHT: 0, SHAKY: 1, WRONG: 2}
TOP = 10
PER_STUDENT = 20          # 一个人的复习单最多放这么多词，最常错的在前


def _s(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, list):
        return "、".join(str(x.get("text", x)) if isinstance(x, dict) else str(x) for x in v)
    return str(v).strip()


def _num(v, d=0):
    try:
        return int(float(_s(v)))
    except ValueError:
        return d


def _split(s):
    return [x.strip() for x in re.split(r"[、,，]", _s(s)) if x.strip()]


def _when(v):
    """提交时间（飞书「创建时间」列）：毫秒数或「2026-11-17 15:20」这样的文字都能比。没有就排最后。"""
    t = _s(v)
    if not t:
        return float("inf")
    try:
        return float(t)
    except ValueError:
        d = re.sub(r"\D", "", t)
        return float(d) if d else float("inf")


def _first_order(r):
    return (_num(r.get("第几次"), 1), _when(r.get("提交时间")))


def key_of(r):
    return f"{_s(r.get('班级'))}·{_s(r.get('姓名'))}"


def rid(en):
    """「我的复习」/ 期末那种按人出词的分页里，题号 = R- + 词（和学生页一样的写法）。"""
    return "R-" + re.sub(r"[^A-Za-z0-9-]+", "_", en)


def _base_of(surface, words):
    s = surface.lower()
    if s in words:
        return words[s]
    for w in sorted(words, key=len, reverse=True):          # devoted → devote，studies → study
        stem = w[:-1] if w[-1:] in "ey" and len(w) > 3 else w
        if s.startswith(stem):
            return words[w]
    return None


class PackInfo:
    """一个包：题号 → 词、完形变形 → 原词、这一课考了哪些词、中文。"""

    def __init__(self, pk):
        self.id_word, self.surface, self.zh, self.vocab = {}, {}, {}, []
        self.per_student = pk.get("schema") == "beike-words/1"
        self.all, self.who = pk.get("all") or [], pk.get("who") or {}
        if self.per_student:
            for en, it in (pk.get("words") or {}).items():
                self.id_word[rid(en)] = en
                self.zh[en] = it.get("zh", "")
            return
        items = pk.get("items") or {}
        lower = {}
        for iid, it in items.items():
            if it.get("type") == "word" and it.get("en"):
                self.id_word[iid] = it["en"]
                self.zh[it["en"]] = it.get("zh", "")
                lower[it["en"].lower()] = it["en"]
                self.vocab.append(it["en"])
        for iid, it in items.items():
            if it.get("type") == "cloze":
                w = it.get("word") or _base_of(it.get("answer", ""), lower)
                if w:
                    self.id_word[iid] = w
                    if it.get("answer"):
                        self.surface[it["answer"].lower()] = w

    def vocab_for(self, key):
        return (self.all + list(self.who.get(key, []))) if self.per_student else self.vocab


def _order(home):
    """packId → 排先后用的键（日期, 第几课）。课目录里有的按首发日期和第几课；没有的从 packId 里找日期。"""
    out = {}
    for e in units.lessons(home, 含撤了=True):
        day = str(e.get("首发") or e.get("发布时间") or "")[:10]
        out[e["packId"]] = (day or "9999", e.get("第几课") or 10 ** 6)
    return out


def _day_from_id(pid):
    m = re.search(r"(20\d{2})(\d{2})(\d{2})", pid)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else "9999"


def _r_word(iid, rmap):
    """「我的复习」那种按人出词的题号 R-词：没有那个包（现查的复习单不在这台电脑上）也能对回词。"""
    return (rmap or {}).get(iid) or iid[2:].replace("_", " ")


def _outcomes(r, info, vocab, key, rmap=None):
    """这一份交上来的里面，每个词第一遍的结果（同一个词出现在几道题里，取最差的）。
    review-api/rules.mjs 里有一份一样的（学生页「我的复习」现查用），改这里要一起改。"""
    out = {}

    def put(w, o):
        if w and (w not in out or _RANK[o] > _RANK[out[w]]):
            out[w] = o
    detail = _s(r.get("明细"))
    ids = info.id_word if info else {}
    if detail and (ids or "R-" in detail):
        for part in detail.split(","):
            if ":" not in part:
                continue
            iid, res = part.split(":", 1)
            iid = iid.strip()
            w = ids.get(iid) or (_r_word(iid, rmap) if iid.startswith("R-") else None)
            o = _RES.get(res.split(">")[0].strip())
            if w and o:
                put(w, o)
        if out:
            return out
    # 没有明细（表单太长时会丢）或者这一课的题找不到：从两个清单反推，其余考过的词算对
    surface = info.surface if info else {}
    lower = {w.lower(): w for w in vocab}

    def norm(lab):
        if not WORD_RE.fullmatch(lab):
            return None
        return surface.get(lab.lower()) or lower.get(lab.lower()) or lab
    for lab in _split(r.get("还不会清单")):
        put(norm(lab), WRONG)
    for lab in _split(r.get("差一点清单")):
        put(norm(lab), SHAKY)
    for w in vocab:
        put(w, RIGHT)
    return out


def compute(records, home=None, vocab=None, pack=None, zh=None):
    """records：成绩表的行（飞书拉下来的或 collect.parse 出来的都行）。
    vocab：{packId: [英文词…]}，课目录里没有的包靠它知道考了哪些词。
    pack：全班前 10 算哪一课，默认有人交过的最近一课。zh：{英文: 中文}，补中文用。"""
    packs = units.all_packs(home)
    info = {pid: PackInfo(pk) for pid, pk in packs.items()}
    order = _order(home)
    vocab = vocab or {}
    zh_all = {}
    for w, z in (zh or {}).items():
        if z:
            zh_all[w] = z
    for pi in info.values():
        zh_all.update({w: z for w, z in pi.zh.items() if z})
    rmap = {rid(w): w for ws in vocab.values() for w in ws}
    rmap.update({rid(w): w for w in zh_all})
    rmap.update({rid(w): w for pi in info.values() for w in pi.id_word.values()})

    def okey(pid):
        return order.get(pid) or (_day_from_id(pid), 10 ** 6)

    rows = [r for r in records if _s(r.get("姓名")) and _s(r.get("内容包"))]
    by = defaultdict(list)
    for r in rows:
        by[(key_of(r), _s(r.get("内容包")))].append(r)

    # ── 每个人：每一课第一份不偏短的，按课的先后过一遍
    events = defaultdict(list)
    for (k, pid), rs in by.items():
        rs = sorted(rs, key=_first_order)
        good = next((r for r in rs if _s(r.get("用时偏短")) != "是"), None)
        if not good:
            continue
        pi = info.get(pid)
        voc = pi.vocab_for(k) if pi else []
        voc = voc or list(vocab.get(pid, []))
        events[k].append((okey(pid), pid, _outcomes(good, pi, voc, k, rmap)))
    students = {}
    for k, evs in events.items():
        mine = {}
        for _, pid, outs in sorted(evs, key=lambda e: (e[0], e[1])):      # 同一天同一位置的按 packId，两边算出来才一样
            for w, o in outs.items():
                s = mine.get(w)
                if o != RIGHT:
                    s = mine.setdefault(w, {"状态": o, "错在哪几课": [], "连续对几次": 0})
                    s["状态"], s["连续对几次"] = o, 0
                    if pid not in s["错在哪几课"]:
                        s["错在哪几课"].append(pid)
                elif s and s["状态"] != "拿下":
                    s["连续对几次"] += 1
                    if s["连续对几次"] >= 2:
                        s["状态"] = "拿下"
        students[k] = mine

    # ── 全班前 10：这一课，每个人第一次交的那份（偏短的也算，和看板一样）
    regular = {pid for (_, pid) in by if not (info.get(pid) and info[pid].per_student)}
    this = pack or (max(regular, key=okey) if regular else "")
    agg = {}
    pi = info.get(this)
    lower = {w.lower(): w for w in (pi.vocab if pi else vocab.get(this, []))}
    for (k, pid), rs in by.items():
        if pid != this:
            continue
        first = min(rs, key=_first_order)

        def base(lab):
            if not WORD_RE.fullmatch(lab):
                return None
            return (pi.surface.get(lab.lower()) if pi else None) or lower.get(lab.lower()) or lab
        nope = [w for w in map(base, _split(first.get("还不会清单"))) if w]
        shaky = [w for w in map(base, _split(first.get("差一点清单"))) if w]
        for w in dict.fromkeys(nope + shaky):
            a = agg.setdefault(w, {"词": w, "人数": 0, "还不会": 0, "差一点": 0})
            a["人数"] += 1
            a["还不会" if w in nope else "差一点"] += 1
    top = sorted(agg.values(), key=lambda a: (-(2 * a["还不会"] + a["差一点"]), a["词"]))[:TOP]
    return {"学生": students, "全班": top, "这一课": this, "中文": zh_all}


def review_lists(model, 去掉=()):
    """每人还没拿下的词：错的课越多越靠前。"""
    drop = {w.lower() for w in 去掉}
    out = {}
    for k, ws in model["学生"].items():
        mine = [w for w, s in ws.items() if s["状态"] != "拿下" and w.lower() not in drop]
        mine.sort(key=lambda w: (-len(ws[w]["错在哪几课"]), w))
        if mine:
            out[k] = mine
    return out


# ── 复习设置（学期级：老师说的「去掉 / 加上」一直管用；「关掉」只管下一次发）────────
def settings_path(home=None):
    return units.home_dir(home) / "复习设置.json"


def load_settings(home=None):
    """{"去掉": [...], "加上": [...], "中文": {加上的词: 中文}, "下次关掉": bool}。
    第一次用时，从老的复习计划里把还有效的去掉 / 加上搬过来。"""
    try:
        d = json.loads(settings_path(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old = load_plan(home) or {}
        live = old.get("状态") != "已用"
        d = {"去掉": old.get("去掉", []) if live else [], "加上": old.get("加上", []) if live else [],
             "中文": {}, "下次关掉": live and old.get("状态") == "关掉"}
    for k in ("去掉", "加上"):
        d[k] = [w for w in d.get(k) or [] if _s(w)]
    d["中文"] = d.get("中文") or {}
    d["下次关掉"] = bool(d.get("下次关掉"))
    return d


def save_settings(d, home=None):
    d["改于"] = time.strftime("%Y-%m-%d %H:%M")
    f = settings_path(home)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(f)


def apply_settings(p, home=None):
    """把学期级设置套到复习计划上（去掉 / 加上 / 关掉），重算每人，存起来。返回 p。"""
    st = load_settings(home)
    p["去掉"], p["加上"] = st["去掉"], st["加上"]
    p["状态"] = "关掉" if st["下次关掉"] else "已排好"
    p.setdefault("中文", {})
    refresh(p)
    for w, z in st["中文"].items():
        if z and w in p.get("加上", []):
            p["中文"].setdefault(w, z)
    p["每人"] = {k: [w for w in ws if p["中文"].get(w)] for k, ws in p["每人"].items()}
    p["每人"] = {k: ws for k, ws in p["每人"].items() if ws}
    return p


# ── 复习计划 ───────────────────────────────────────
def plan_path(home=None):
    return units.home_dir(home) / "复习计划.json"


def load_plan(home=None):
    try:
        return json.loads(plan_path(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save_plan(p, home=None):
    f = plan_path(home)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(p, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(f)


def class_words(p):
    """全班最卡的词（给老师课上讲）：算出来的前 10 去掉老师说不要的。「加上」的词进每个人的单子，不算在这里。"""
    drop = {w.lower() for w in p.get("去掉", [])}
    return [w for w in p.get("算出来的", []) if w.lower() not in drop]


def refresh(p):
    """老师只改全班层面的事：「去掉」从每个人的复习单里拿掉；「加上」给每个还没拿下它的人都加上。
    「全班」只是全班最卡的词，给老师课上讲，不进学生的网页。"""
    p["全班"] = class_words(p)
    drop = {w.lower() for w in p.get("去掉", [])}
    got = {k: {w.lower() for w in ws} for k, ws in p.get("拿下", {}).items()}
    每人 = {k: [w for w in ws if w.lower() not in drop] for k, ws in p.get("每人算出来的", {}).items()}
    for w in p.get("加上", []):
        for k in p.get("学生们", []):
            mine = 每人.setdefault(k, [])
            if w.lower() not in got.get(k, set()) and w.lower() not in {x.lower() for x in mine}:
                mine.append(w)
    p["每人"] = {k: ws for k, ws in 每人.items() if ws}
    return p


def draft_plan(model, 来自="收", home=None):
    """收完作业（或看完看板）排好复习计划。不用老师确认；老师说过的「去掉 / 加上」（学期级）照样套上。
    返回给老师的一两句话。"""
    old = load_plan(home) or {}
    zh = model.get("中文", {})
    per = {k: [w for w in ws if zh.get(w)][:PER_STUDENT] for k, ws in review_lists(model).items()}
    got = {k: sorted(w for w, s in ws.items() if s["状态"] == "拿下") for k, ws in model["学生"].items()}
    # 上次排进复习单的词，这次拿下了几个（一个人一个词算一个）
    before = old.get("每人算出来的") or {}
    back = sum(1 for k, ws in before.items() for w in ws if w in got.get(k, ()))
    p = {"生成于": time.strftime("%Y-%m-%d %H:%M"), "来自": 来自, "这一课": model.get("这一课", ""),
         "算出来的": [a["词"] for a in model.get("全班", [])],
         "每人算出来的": per, "学生们": sorted(model["学生"]), "拿下": {k: v for k, v in got.items() if v},
         "上次拿下": back if before else None, "中文": {w: z for w, z in zh.items() if z}}
    apply_settings(p, home)             # 中文整份留着：以后说「加上」一个以前的词时还要用
    save_plan(p, home)
    return plan_sentence(p)


def plan_sentence(p):
    """给老师的一两句话：只讲整体，不列人。"""
    if p["状态"] == "关掉":
        return "复习计划更新了。你说过下次发新课不带「我的复习」，发完那一次就自动恢复。"
    per = p["每人"]
    n = len(per)
    parts = []
    if n:
        avg = sum(len(ws) for ws in per.values()) / n
        parts.append(f"系统给 {n} 人排了自己的复习，平均每人 {avg:.0f} 个词")
    else:
        parts.append("这次没有人需要自己复习")
    if p.get("上次拿下") is not None:
        parts.append(f"上次的错词拿下了 {p['上次拿下']} 个")
    s = "；".join(parts) + "。"
    if p["全班"]:
        s += f"全班最卡的是 {'、'.join(p['全班'][:3])}，适合课上讲。"
    return s + "不用你确认；想改就说，比如「devote 不用复习了」「加上 malaria」（说一次，这学期一直管用）。"


def main():
    import argparse
    ap = argparse.ArgumentParser(description="算每个学生哪些词还没拿下（自己核对用，不写任何东西）")
    ap.add_argument("src", help="成绩 json（行的数组，或 {records: [...]}）或带 BK2| 结果码的文本")
    ap.add_argument("--home")
    ap.add_argument("--谁", dest="who")
    ap.add_argument("--pack")
    a = ap.parse_args()
    text = Path(a.src).read_text(encoding="utf-8")
    vocab, zh = {}, {}
    try:
        d = json.loads(text)
        recs = d.get("records", []) if isinstance(d, dict) else d
        for w in (d.get("words", []) if isinstance(d, dict) else []):
            vocab.setdefault(w["内容包"], []).append(w["词"])
            zh[w["词"]] = w.get("中文", "")
    except ValueError:
        import collect
        recs = collect.parse(text)
    m = compute(recs, home=a.home, vocab=vocab, pack=a.pack, zh=zh)
    print(f"这一课：{m['这一课']}　全班前 {len(m['全班'])}：" +
          "、".join(f"{x['词']} {x['人数']}人" for x in m["全班"]))
    rl = review_lists(m)
    print(f"{len(rl)} 个人有没拿下的词")
    for k in ([a.who] if a.who else list(rl)[:5]):
        print(f"  {k}：", json.dumps(m["学生"].get(k, {}), ensure_ascii=False))


if __name__ == "__main__":
    main()
