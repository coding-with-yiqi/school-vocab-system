#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
词表 → 背课包（pack.json）

设计目标：老师不耗 token。
关卡玩法是写死的模板，这个脚本只做"填空"——把课本本来就有的词表、句子、错题
按模板排进 5 个关卡。全程纯 Python，不调用任何大模型。

用法：
    python3 build_pack.py 词表.md -o pack.json
    python3 build_pack.py 词表.md -o pack.json --episode 剧情.json
    python3 build_pack.py 词表.md -o pack.json --review 错题池.json   # 错题优先回流

词表格式（老师直接从课本词表粘，一行一个，| 分隔）：

    # Unit 1 People of Achievement
    ## 词
    achievement | 成就；功绩
    devote to | 致力于；献身于
    ## 句
    He devoted his whole life to the cause. | 他把一生都奉献给了这项事业。
    ## 错
    He devote his life to science. | He devoted his life to science. | 时态
"""
import argparse, json, random, re, sys
from datetime import date
from pathlib import Path

REASONS = ["时态", "词性", "搭配", "拼写"]
# 词表里的段标题（## 词 / ## 句 / ## 错 和它们的别名）→ 题型。wordlist.py 查词表也用这一份。
SECTIONS = {"词": "word", "单词": "word", "短语": "word",
            "句": "sentence", "句子": "sentence", "例句": "sentence",
            "错": "fix", "错题": "fix", "改错": "fix"}


def parse_wordlist(text):
    """把老师的词表切成 词/句/错 三段。段标题认 '## 词' '## 句' '## 错'。"""
    title, sec = "", None
    out = {"word": [], "sentence": [], "fix": []}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("<!--"):
            continue
        if line.startswith("##"):
            key = line.lstrip("#").strip()
            sec = SECTIONS.get(key, SECTIONS.get(key[:1]))
            continue
        if line.startswith("#"):
            title = line.lstrip("#").strip()
            continue
        parts = [p.strip() for p in re.split(r"\s*[|｜]\s*", line) if p.strip()]
        if sec and len(parts) >= 2:
            out[sec].append(parts)
    return title, out


def hint_of(en):
    """achievement -> ach_______t：露头尾，中间打码，给个台阶但不白给。"""
    body = en.split()[0]
    if len(body) <= 3:
        return body[0] + "_" * (len(body) - 1)
    keep = 3 if len(body) >= 8 else 2
    return body[:keep] + "_" * (len(body) - keep - 1) + body[-1]


def accept_of(en):
    """接受形：原形 + 复数 + 过去式。

    只加这两种。别乱加 es/ees——devote 加出 devotees 是另一个真词，
    会把学生写错的judge成对，比判错更糟。
    """
    acc = {en.lower()}
    head = en.split()[0].lower()
    acc.add(head)
    if head.isalpha():
        acc.add(head + "s")
        acc.add(head + "d" if head.endswith("e") else head + "ed")
    return sorted(acc)


def make_cloze(sentences, words, rng):
    """从例句里挖掉目标词 → 情境填空；干扰项从同包其他词里取。"""
    out, pool = [], [w[0].split()[0] for w in words]
    for en, zh in sentences:
        hit = next((w for w in words
                    if re.search(r"\b" + re.escape(w[0].split()[0]), en, re.I)), None)
        if not hit:
            continue
        m = re.search(r"\b" + re.escape(hit[0].split()[0]) + r"\w*", en, re.I)
        # 答案用句子里真正出现的那个形（devoted，不是 devote），
        # 否则学生"选对了"却读出一个语法错的句子。
        surface = m.group(0)
        ctx = en[:m.start()] + "____" + en[m.end():]
        distract = [p for p in pool if not surface.lower().startswith(p.lower())]
        rng.shuffle(distract)
        opts = [surface] + distract[:3]
        rng.shuffle(opts)
        # word：这道填空考的是词表里哪个词。learning.py 靠它把 devoted 算到 devote 头上。
        out.append({"type": "cloze", "context": ctx, "answer": surface, "word": hit[0],
                    "accept": [surface.lower()], "options": opts, "zh": zh})
    return out


def build(title, data, episode, review_ids, seed=7, known=None, carry=5):
    rng = random.Random(seed)
    items, idx = {}, {"W": 0, "C": 0, "P": 0, "E": 0, "S": 0}

    def add(kind, obj):
        idx[kind] += 1
        key = f"{kind}-{idx[kind]:03d}"
        items[key] = obj
        return key

    words = [w[:2] for w in data["word"]]
    carried = []
    # 错题回流：上次没背下来的词排到最前面，学生一打开先撞见它。
    # 这次词表里有的，挪到前面；这次词表里没有的（上一课的词），从以前发过的包里
    # 找回中文，最多带 carry 个加进来。找不到中文的不带——没有中文出不了题。
    if review_ids:
        here = {w[0].lower() for w in words}
        for r in review_ids:
            k = r.lower()
            if k not in here and known and k in known and len(carried) < carry:
                carried.append(list(known[k]))
                here.add(k)
        want = {r.lower() for r in review_ids}
        words = (carried + [w for w in words if w[0].lower() in want] +
                 [w for w in words if w[0].lower() not in want])

    word_ids = [add("W", {"type": "word", "zh": zh, "en": en,
                          "accept": accept_of(en), "hint": hint_of(en)})
                for en, zh in words]
    cloze_ids = [add("C", c) for c in make_cloze(data["sentence"], words, rng)]
    sent_ids = [add("S", {"type": "sentence", "zh": "请默写：" + zh, "answer": en,
                          "accept": [re.sub(r"[.,!?;:]", "", en.lower()).strip()],
                          "keys": [en.split()[1]] if len(en.split()) > 1 else []})
                for en, zh in data["sentence"]]
    fix_ids = []
    for row in data["fix"]:
        wrong, right = row[0], row[1]
        reason = row[2] if len(row) > 2 else "搭配"
        fix_ids.append(add("E", {"type": "fix", "wrong": wrong, "answer": right,
                                 "accept": [re.sub(r"[.,!?;:]", "", right.lower()).strip()],
                                 "reason": reason, "reasons": REASONS}))
    compose_ids = []
    if len(word_ids) >= 2:
        must = [items[word_ids[0]]["en"].split()[0], items[word_ids[1]]["en"].split()[0]]
        compose_ids.append(add("P", {
            "type": "compose",
            "prompt": f"用 {must[0]} 和 {must[1]}，自己写一句靠谱的话——讲得通，也说得对。",
            "must": must, "minWords": 8}))

    scenes = episode["scenes"]
    plan = [("flash", word_ids, "闪认 · 看中文拼英文"),
            ("cloze", cloze_ids, "情境填空 · 把词放回剧情"),
            ("compose", compose_ids, "造句 · 用这些词讲一句靠谱的话"),
            ("fix", fix_ids, "改错 · 改对，并说清为什么"),
            ("recall", sent_ids, "默写 · 作文里能直接用的句子")]

    levels, n = [], 0
    for kind, ids, label in plan:
        if not ids:
            continue
        chunk = ids  # 词表里放了多少就考多少：考哪些、考几个，老师在词表里定
        levels.append({"id": f"L{n+1}", "sceneId": scenes[min(n, len(scenes) - 1)]["id"],
                       "type": kind, "title": label,
                       "pass": max(1, int(len(chunk) * 0.8)), "items": chunk})
        n += 1

    used = {i for l in levels for i in l["items"]}
    return {
        "packId": f"{re.sub(r'[^A-Za-z0-9]+', '-', title).strip('-') or 'PACK'}-{date.today():%Y%m%d}",
        "schema": "beike-pack/1",
        "title": title or "背课包",
        "subtitle": episode.get("subtitle", ""),
        "source": {"from": "课本词表 / WorkBuddy 备课资料",
                   "generatedBy": "beike-memory skill v1",
                   "generatedAt": str(date.today()),
                   "reviewFirst": bool(review_ids),
                   "reviewCarried": [w[0] for w in carried]},
        "submit": {"formUrl": "", "fieldMap": {
            "student": "学生", "packId": "内容包", "passed": "通过数", "near": "接近数",
            "failed": "未通过数", "wrongList": "未通过清单", "selfRating": "学生自评",
            "needTeacher": "需老师看", "durationSec": "用时秒", "detail": "明细"}},
        "episode": episode,
        "levels": levels,
        "items": {k: v for k, v in items.items() if k in used},
    }


def load_known(*folders):
    """从以前发过的包里收集 英文→(英文, 中文)，新包覆盖旧包。
    认两种地方：发布目录里的 pack-*.json，课目录里的 <packId>/pack.json（含「我的复习」那种按人出词的包）。"""
    known = {}
    files = []
    for folder in folders:
        if folder and Path(folder).exists():
            files += list(Path(folder).glob("pack-*.json")) + list(Path(folder).glob("*/pack.json"))
    for f in sorted(files, key=lambda f: f.stat().st_mtime):
        try:
            pk = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        for it in (pk.get("items") or {}).values():
            if it.get("type") == "word" and it.get("en") and it.get("zh"):
                known[it["en"].lower()] = (it["en"], it["zh"])
        for en, it in (pk.get("words") or {}).items():
            if it.get("zh"):
                known[en.lower()] = (en, it["zh"])
    return known


def review_from(path):
    """--review 可以给两种：错题池（字符串数组），或者复习计划.json（取「全班」那几个词）。"""
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(d, dict):
        return [] if d.get("状态") == "关掉" else list(d.get("全班") or [])
    return list(d or [])


DEFAULT_EPISODE = {
    "title": "本周剧情", "tagline": "看一段，过一关，解锁下一段。",
    "scenes": [{"id": f"S{i}", "label": f"第 {i} 幕", "time": "",
                "text": "（把这一幕换成你班上学生在追的剧，或者课文本身的情境。）",
                "cliff": "先过这一关，下一幕解锁。"} for i in range(1, 6)],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("wordlist")
    ap.add_argument("-o", "--out", default="pack.json")
    ap.add_argument("--episode", help="剧情 json，不给就用占位剧情")
    ap.add_argument("--review", help="错题池 json（字符串数组）或复习计划.json，这些词排到最前面")
    ap.add_argument("--history", action="append", default=[],
                    help="以前发过的包所在目录（发布/ 或 课/），用来找回上一课错词的中文。可以给几个。"
                    "不给就用错题池旁边的「发布」和「课」目录")
    ap.add_argument("--carry", type=int, default=5, help="最多带几个上一课的错词进来（默认 5）")
    a = ap.parse_args()

    title, data = parse_wordlist(Path(a.wordlist).read_text(encoding="utf-8"))
    if not any(data.values()):
        sys.exit("词表里什么都没读到。检查一下有没有 '## 词' 这样的段标题。")
    episode = json.loads(Path(a.episode).read_text(encoding="utf-8")) if a.episode else DEFAULT_EPISODE
    review = review_from(a.review) if a.review else []

    hist = a.history or ([Path(a.review).parent / "发布", Path(a.review).parent / "课"] if a.review else [])
    known = load_known(*hist) if hist else {}
    pack = build(title, data, episode, review, known=known, carry=a.carry)
    Path(a.out).write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ {a.out}")
    print(f"  {pack['title']}　{len(pack['levels'])} 关　{len(pack['items'])} 题"
          + ("　（错题优先）" if review else ""))
    if pack["source"]["reviewCarried"]:
        print("  上一课没背下来、这次补进来的词：" + "、".join(pack["source"]["reviewCarried"]))
    for l in pack["levels"]:
        print(f"  - {l['title']}：{len(l['items'])} 题，过 {l['pass']} 题解锁")


if __name__ == "__main__":
    main()
