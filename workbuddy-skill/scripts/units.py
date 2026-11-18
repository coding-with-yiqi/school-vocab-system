# -*- coding: utf-8 -*-
"""课目录：这一学期发过的每一课。学生页按这个目录出分页（第 1 课 / 第 2 课 / …）。

    ~/.beike/课/目录.json          哪几课、第几课、标题、packId、发布时间、撤了没有
    ~/.beike/课/<packId>/pack.json 这一课的背课包（题）
    ~/.beike/课/<packId>/词表.md   这一课的词表（有就存）

「第几课」一旦分配就不变。撤掉的课只是学生页不显示，号不重排，成绩和存档都还在。
同一个 packId 再发一次（比如改了词表重发），换掉那一课的题，第几课不变。

两种课：
- 普通课（类型「课」）：pack.json 就是 build_pack.py 出的背课包，每个学生题一样。
- 按人出词的课（类型「期末」或「复习」）：pack.json 只放词和中文，外加「全班」和「每人」两份词单，
  学生页上每个人只看到 全班 + 自己的词。「我的复习」就是这种，存在目录的「复习」里，不占第几课。

看板、收尾、期末都读这个目录，不另存一套。
"""
import json, os, re, shutil, time
from pathlib import Path


def home_dir(home=None):
    return Path(home) if home else Path(os.path.expanduser(os.environ.get("BEIKE_HOME", "~/.beike")))


def _dir(home=None):
    return home_dir(home) / "课"


def _safe(pid):
    return re.sub(r'[\\/:*?"<>|\s]+', "_", str(pid)) or "PACK"


def load(home=None):
    try:
        d = json.loads((_dir(home) / "目录.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    d.setdefault("课", [])
    d.setdefault("复习", None)
    return d


def save(d, home=None):
    p = _dir(home)
    p.mkdir(parents=True, exist_ok=True)
    tmp = p / "目录.json.tmp"
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p / "目录.json")


def lessons(home=None, 含撤了=False, 含试做=True):
    """按第几课排好的条目。学生页用 含撤了=False；看板想把撤了的灰着列出来用 含撤了=True。"""
    out = [e for e in load(home)["课"]
           if (含撤了 or not e.get("撤了")) and (含试做 or not e.get("试做"))]
    return sorted(out, key=lambda e: e.get("第几课", 0))


def pack(pid, home=None):
    try:
        return json.loads((_dir(home) / _safe(pid) / "pack.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def all_packs(home=None):
    """目录里出现过的每一个包（含撤了的、复习的），packId → pack。learning.py 用来把题号对回词。"""
    out = {}
    d = _dir(home)
    if not d.exists():
        return out
    for f in d.glob("*/pack.json"):
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if p.get("packId"):
            out[p["packId"]] = p
    return out


def find(n, home=None):
    """按「第几课」找条目（n 可以是数字、「第 2 课」、或 packId）。"""
    s = str(n).strip()
    es = load(home)["课"]
    hit = next((e for e in es if e["packId"] == s), None)
    if hit:
        return hit
    m = re.fullmatch(r"第?\s*(\d+)\s*课?", s)
    if m:
        return next((e for e in es if e.get("第几课") == int(m.group(1))), None)
    return next((e for e in es if s and str(e.get("标题", "")).lower().startswith(s.lower())), None)


def _now():
    return time.strftime("%Y-%m-%d %H:%M")


def _put(entry_fields, pk, home, wordlist=None):
    d = load(home)
    pid = pk["packId"]
    folder = _dir(home) / _safe(pid)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "pack.json").write_text(json.dumps(pk, ensure_ascii=False, indent=1), encoding="utf-8")
    if wordlist and Path(wordlist).exists():
        shutil.copyfile(wordlist, folder / "词表.md")
    old = next((e for e in d["课"] if e["packId"] == pid), None)
    if old:
        keep_title = old.get("改过名")
        old.update(entry_fields)
        if keep_title:
            old["标题"] = old["改过名"]
        old["撤了"] = False
        e = old
    else:
        n = max([x.get("第几课", 0) for x in d["课"]] + [0]) + 1
        e = dict(entry_fields, 第几课=n, packId=pid, 撤了=False, 首发=_now())   # 首发不变，learning.py 按它排先后
        d["课"].append(e)
    save(d, home)
    return e


def add(pk, wordlist=None, 试做=False, home=None):
    """发一课：把背课包放进目录。返回条目（里面有第几课）。
    试做=True 是「只生成、没发布」的：只生成的网页里有它，真发布的网页里没有，直到真发一次。"""
    old = next((e for e in load(home)["课"] if e["packId"] == pk["packId"]), None)
    fields = {"标题": pk.get("title") or pk["packId"], "发布时间": _now(), "类型": "课",
              "试做": bool(试做) and not (old and not old.get("试做"))}
    return _put(fields, pk, home, wordlist)


def mark_sent(pid, home=None):
    d = load(home)
    for e in d["课"]:
        if e["packId"] == pid:
            e["试做"] = False
            e["发布时间"] = _now()
    save(d, home)


def word_item(en, zh):
    """一个「看中文拼英文」的题。和 build_pack 的闪认关同一个判法。"""
    import build_pack
    return {"zh": zh, "accept": build_pack.accept_of(en), "hint": build_pack.hint_of(en)}


def word_pack(pid, 标题, 词, 全班=(), 每人=None, 类型="复习", 说明=""):
    return {"packId": pid, "schema": "beike-words/1", "title": 标题, "kind": 类型, "note": 说明,
            "words": {en: word_item(en, zh) for en, zh in 词.items() if en and zh},
            "all": [w for w in 全班 if 词.get(w)],
            "who": {k: [w for w in ws if 词.get(w)] for k, ws in (每人 or {}).items()}}


def add_word_pack(packId, 标题, 词, 全班=(), 每人=None, 类型="期末", 说明="", 试做=False, home=None):
    """加一课「按人出词」的分页（期末复习用这个）。词 = {英文: 中文}；全班 = [英文…]；
    每人 = {"高一3班·林小雨": [英文…]}。学生页上每个人只看到 全班 + 自己的词。返回条目。"""
    pk = word_pack(packId, 标题, 词, 全班, 每人, 类型, 说明)
    return _put({"标题": 标题, "发布时间": _now(), "类型": 类型, "试做": bool(试做)}, pk, home)


def set_review(packId, 词, 每人, home=None):
    """「我的复习」：每个人自己没拿下的词。不占第几课，学生页上放在最前面。每人为空就撤掉。"""
    d = load(home)
    if not any(每人.values()):
        d["复习"] = None
        save(d, home)
        return None
    pk = word_pack(packId, "我的复习", 词, (), 每人, "复习",
                   "这些是你前几课没拿下的词。每个词连续两次第一遍就写对，就从这里消失。")
    folder = _dir(home) / _safe(packId)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "pack.json").write_text(json.dumps(pk, ensure_ascii=False, indent=1), encoding="utf-8")
    d["复习"] = {"packId": packId, "标题": "我的复习", "发布时间": _now(), "类型": "复习",
               "人数": sum(1 for v in 每人.values() if v)}
    save(d, home)
    return d["复习"]


def hide(n, home=None, undo=False):
    hit = find(n, home)
    if not hit:
        return None
    d = load(home)
    e = next(x for x in d["课"] if x["packId"] == hit["packId"])
    e["撤了"] = not undo
    save(d, home)
    return e


def rename(n, title, home=None):
    hit = find(n, home)
    if not hit:
        return None
    d = load(home)
    e = next(x for x in d["课"] if x["packId"] == hit["packId"])
    e["标题"] = e["改过名"] = title
    save(d, home)
    return e


def label(e):
    """学生页和输出里怎么叫这一课。"""
    if e.get("类型") == "期末":
        return e.get("标题") or "期末复习"
    return f"第 {e.get('第几课')} 课"
