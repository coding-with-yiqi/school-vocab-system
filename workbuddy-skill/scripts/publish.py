#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pack.json + 网页模板 → 一个可以直接发给学生的单文件 HTML

单文件 = 没有依赖、没有后端、手机点开就能玩、断网也能继续。
网页里不含任何密钥，所以随便发群里都安全。

一个班一个网页：班级写死在页面里，名单烧进下拉菜单，
学生选自己的名字就行。这样班级零歧义、姓名零错字。

两种用法：
- 一课一个网页（老办法）：给一个 pack.json。
- 整个课目录一个网页（beike.py 发 用这个）：--book ~/.beike/课。目录里每一课都是一个分页
  （第 1 课 / 第 2 课 / …），最新的一课默认打开、标「新」；有「我的复习」就放最前面。
  每一课的进度在学生手机上按 packId 分开存，切来切去不丢。

用法：
    python3 publish.py --book ~/.beike/课 -o 背单词闯关.html --roster 名单.txt --form "…"
    python3 publish.py pack.json -o 作业_Unit1.html
    python3 publish.py pack.json -o 高一3班_Unit1.html \
            --class 高一3班 --roster 高一3班名单.txt \
            --form "https://<你的飞书域名>/share/base/shrcnXXXX"
"""
import argparse, json, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import roster  # noqa: E402

# 模板随 skill 一起装（assets/student.html）。在开发仓库里跑时，
# 旁边还有 04_工程/student/index.html，两份取较新的那份，改了模板不用手动同步。
_HERE = Path(__file__).resolve().parent
_CANDIDATES = [p for p in (_HERE.parent / "assets" / "student.html",
                           _HERE.parents[1] / "student" / "index.html") if p.exists()]
TPL = max(_CANDIDATES, key=lambda p: p.stat().st_mtime) if _CANDIDATES \
    else _HERE.parent / "assets" / "student.html"
START, END = "/*__PACK_START__*/", "/*__PACK_END__*/"
FULL_EPISODES = 15      # 超过这么多课，更早的课把剧情文字去掉（题都留着），网页小一点，手机流量下也快
from contract import WEB_TO_COLUMN as FIELD_MAP  # noqa: E402  学生页 payload() 的键 → 成绩表的列


def book(home, rosters, include_trial=False):
    """课目录 → 一个「书」：所有没撤的课 + 我的复习。每人词单的键换成名单里的位置（班序|人序），
    不把「谁错了哪些词」直接按名字写在网页源码里。"""
    import units
    es = [e for e in units.lessons(home) if include_trial or not e.get("试做")]
    packs, personal, missing = [], [], []
    classes = [c for c, ns in rosters.items() if ns]
    pos = {f"{c}·{n}": f"{ci}|{ni}" for ci, c in enumerate(classes) for ni, n in enumerate(rosters[c])}

    def personal_of(pk, e, first=False):
        who = {pos[k]: ws for k, ws in (pk.get("who") or {}).items() if k in pos and ws}
        return {"packId": pk["packId"], "title": e.get("标题") or pk.get("title"), "kind": pk.get("kind"),
                "no": e.get("第几课"), "label": "我的复习" if first else units.label(e),
                "note": pk.get("note", ""), "words": pk.get("words") or {}, "all": pk.get("all") or [],
                "who": who, "first": first}

    rv = units.load(home).get("复习")
    if rv:
        pk = units.pack(rv["packId"], home)
        if pk:
            personal.append(personal_of(pk, rv, first=True))
    for e in es:
        pk = units.pack(e["packId"], home)
        if not pk:
            missing.append(units.label(e))
            continue
        if pk.get("schema") == "beike-words/1":
            personal.append(personal_of(pk, e))
            continue
        pk = dict(pk)
        for k in ("rosters", "roster", "submit", "cls"):
            pk.pop(k, None)
        pk["title"] = e.get("标题") or pk.get("title")
        pk["no"], pk["label"] = e.get("第几课"), units.label(e)
        packs.append(pk)
    order = sorted(packs + [w for w in personal if not w["first"]], key=lambda x: x["no"] or 0)
    if len(packs) > FULL_EPISODES:
        for p in packs[:-FULL_EPISODES]:
            ep = dict(p.get("episode") or {})
            ep["scenes"] = [dict(sc, text="", cliff="") for sc in ep.get("scenes", [])]
            p["episode"], p["trimmed"] = ep, True
    return {"schema": "beike-book/1", "newest": order[-1]["packId"] if order else "",
            "tabs": [x["packId"] for x in order],
            "packs": packs, "personal": personal, "missing": missing}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pack", nargs="?", help="一课的 pack.json（和 --book 二选一）")
    ap.add_argument("--book", help="课目录（~/.beike/课），把目录里每一课都放进这一个网页")
    ap.add_argument("--include-trial", action="store_true", help="--book 时把「只生成过、还没发」的课也放进去")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--form", default="", help="飞书多维表格表单的分享链接")
    ap.add_argument("--class", dest="cls", default="",
                    help="名单文件里没写班级的人，算哪个班")
    ap.add_argument("--roster", action="append", default=[],
                    help="名单文件，可以给好几个，也可以一个文件装几个班。"
                         "学生从下拉里选自己，班级跟着名字走")
    ap.add_argument("--review-api", default="", help="「我的复习」现查的后端地址（方案 A）。给了就不把任何人的复习单放进网页")
    ap.add_argument("--review-drop", default="", help="老师说不用复习的词，逗号隔开（全班一样）")
    ap.add_argument("--review-add", default="", help="老师说给每个没拿下的人加上的词，逗号隔开（全班一样）")
    ap.add_argument("--template", default=str(TPL))
    ap.add_argument("--no-hint", action="store_true", help="不打印下一步提示（beike.py 调用时用）")
    a = ap.parse_args()

    tpl = Path(a.template)
    if not tpl.exists():
        sys.exit(f"找不到网页模板：{tpl}")
    html = tpl.read_text(encoding="utf-8")
    if a.book and "beike-book/1" not in html:
        # 旁边那份老模板只认一课一包；整个课目录要用 skill 自带的新模板
        tpl = _HERE.parent / "assets" / "student.html"
        html = tpl.read_text(encoding="utf-8")
    if START not in html or END not in html:
        sys.exit("模板里找不到内容包占位符，别手改模板里的 __PACK_START__ / __PACK_END__。")

    if a.book:
        rs = roster.read(a.roster, default_cls=a.cls) if a.roster else {}
        pack = book(Path(a.book).parent, rs, a.include_trial)
        if not pack["tabs"]:
            sys.exit("课目录里还没有课。先「beike.py 发」一课。")
        pack["submit"] = {"formUrl": a.form, "fieldMap": FIELD_MAP}
        if a.review_api:
            # 方案 A：网页里不放任何人的单子。学生点开「我的复习」才拿自己的班级 + 名字去后端查。
            words = lambda t: [w.strip() for w in t.split(",") if w.strip()]  # noqa: E731
            pack["personal"] = [w for w in pack["personal"] if not w.get("first")]
            pack["review"] = {"api": a.review_api, "去掉": words(a.review_drop), "加上": words(a.review_add)}
    elif a.pack:
        pack = json.loads(Path(a.pack).read_text(encoding="utf-8"))
    else:
        sys.exit("给一个 pack.json，或者 --book 课目录。")
    if a.form:
        pack.setdefault("submit", {})["formUrl"] = a.form
    # 几个班装进同一个网页：部署一次，同一个链接发几个班群。
    # 飞书托管时页面在跨域 iframe 里，外层链接的 ?c= 传不进来，
    # 所以班级不能靠链接区分，只能靠「选了谁」。
    pack.pop("roster", None)
    if a.roster:
        rs = roster.read(a.roster, default_cls=a.cls)
        if not any(rs.values()):
            sys.exit(f"名单文件是空的：{'、'.join(a.roster)}")
        if "" in rs and len(rs) > 1:
            sys.exit(f"名单里有 {len(rs[''])} 个人没写班级（比如 {rs[''][0]}）。"
                     "写成「姓名,班级」，或者放到「## 班级」段头底下。")
        pack["rosters"] = dict(rs)
        pack["cls"] = next(iter(rs)) if len(rs) == 1 else ""
    elif a.cls:
        pack["cls"] = a.cls

    form = (pack.get("submit") or {}).get("formUrl", "")
    if form and "/share/base/" not in form:
        print("⚠️  这个链接看着不像多维表格的表单分享链接，学生可能提交不了。")

    blob = json.dumps(pack, ensure_ascii=False, separators=(",", ":"))
    head, rest = html.split(START, 1)
    _, tail = rest.split(END, 1)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(head + START + blob + END + tail, encoding="utf-8")

    kb = out.stat().st_size / 1024
    print(f"✓ {out}　{kb:.0f} KB")
    if a.book:
        tabs = sorted(pack["packs"] + [w for w in pack["personal"] if not w["first"]],
                      key=lambda x: x["no"] or 0)
        print(f"  一共 {len(tabs)} 课：" + "、".join(f"{x['label']} {x['title']}" for x in tabs))
        rv = next((w for w in pack["personal"] if w["first"]), None)
        if pack.get("review"):
            print("  我的复习：点开时现查（网页里没有任何人的单子）")
        elif rv:
            print(f"  我的复习：{len(rv['who'])} 个人有自己要复习的词")
        if pack["missing"]:
            print("  ⚠️ 这几课的题找不到了，没放进去：" + "、".join(pack["missing"]))
        if any(p.get("trimmed") for p in pack["packs"]):
            print(f"  课超过 {FULL_EPISODES} 课，更早的课去掉了剧情文字（题都在），网页小一点。")
    else:
        print(f"  {pack['title']}　{len(pack['levels'])} 关　{len(pack['items'])} 题")
    rs = pack.get("rosters") or {}
    if len(rs) > 1:
        print(f"  一个网页装了 {len(rs)} 个班：" +
              "、".join(f"{c} {len(ns)} 人" for c, ns in rs.items()))
        print("  部署一次，同一个链接发到这几个班群。学生选自己的名字，班级自动跟着走。")
    elif rs:
        c, ns = next(iter(rs.items()))
        print(f"  {c or '（没写班级）'}：{len(ns)} 人，学生从下拉里选自己，不用打字")
    else:
        print("  ⚠️ 没给名单：学生要自己打名字，你会收到错字和重名。建议加 --roster。")
    if form:
        print("  交作业：学生做完点一下，成绩自动填进你的多维表格。")
    else:
        print("  ⚠️ 没给表单链接：学生只能复制结果码发群里，你再用 collect.py 入库。")
    if a.no_hint:
        return
    print("\n  下一步，发布成链接（一次就够，几个班共用一个链接）：")
    print(f"    python3 \"{Path(__file__).resolve().parent / 'deploy.py'}\" \"{out}\"")


if __name__ == "__main__":
    main()
