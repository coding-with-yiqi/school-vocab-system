#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把一课的资料变成「词表格式」，再检查一遍能不能直接拿去发。

老师给的东西五花八门：课文、课本后面的单元词汇表、备课 Word、课件、PDF、拍照。
这个脚本只做两件机械的事，中间「挑词、配句子」由 WorkBuddy 自己读完原文来写：

    python3 wordlist.py 抽 课文.docx 词汇表.pdf 备课.pptx -o 原文.txt
        把文件里的文字抽出来拼成一个 txt。图片抽不了，会提示你自己看图。

    python3 wordlist.py 查 词表.md
        按 build_pack.py 的读法检查词表：哪行会被悄悄丢掉、哪个短语学生拼不出来、
        错因选不到、会出几关几题。有「错误」就改，改到没有为止。

不依赖第三方包。PDF 用系统里的 pdftotext（有就用），.doc 用 macOS 的 textutil。
"""
import argparse, re, shutil, subprocess, sys, zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_pack import parse_wordlist, REASONS, SECTIONS  # noqa: E402

IMG = {".jpg", ".jpeg", ".png", ".heic", ".webp", ".bmp", ".gif"}


# ── 抽 ────────────────────────────────────────────
def read_text(p):
    raw = p.read_bytes()
    for enc in ("utf-8-sig", "gb18030", "utf-16"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def office_text(p, para_tag, text_tag, members):
    """docx / pptx 都是 zip 里的 xml。按段落拼字，不需要装任何包。"""
    out = []
    with zipfile.ZipFile(p) as z:
        names = sorted(n for n in z.namelist() if re.fullmatch(members, n))
        # pptx 的幻灯片按数字排，不按字典序（slide10 不能排在 slide2 前面）
        names.sort(key=lambda n: [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", n)])
        for n in names:
            root = ET.fromstring(z.read(n))
            for para in root.iter():
                if para.tag.endswith(para_tag):
                    s = "".join(t.text or "" for t in para.iter() if t.tag.endswith(text_tag))
                    if s.strip():
                        out.append(s)
            out.append("")
    return "\n".join(out)


def extract(p):
    """返回 (文字, 提示)。抽不了时文字为空，提示说清楚该怎么办。"""
    ext = p.suffix.lower()
    if ext in (".txt", ".md", ".csv", ".tsv"):
        return read_text(p), ""
    if ext == ".docx":
        return office_text(p, "}p", "}t", r"word/document\.xml"), ""
    if ext == ".pptx":
        return office_text(p, "}p", "}t", r"ppt/slides/slide\d+\.xml"), ""
    if ext in (".doc", ".rtf", ".pages") and shutil.which("textutil"):
        r = subprocess.run(["textutil", "-convert", "txt", "-stdout", str(p)],
                           capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout, ""
    if ext == ".pdf":
        if shutil.which("pdftotext"):
            r = subprocess.run(["pdftotext", "-layout", str(p), "-"],
                               capture_output=True, text=True)
            if r.stdout.strip():
                return r.stdout, ""
            return "", "这个 PDF 里没有文字层（多半是扫描件），请你直接看 PDF 的页面，把要用的部分抄下来。"
        return "", "这台电脑没有 pdftotext，请你直接打开 PDF 读，把要用的部分抄下来。"
    if ext in IMG:
        return "", "这是图片，脚本读不了。请你直接看图，把词汇表或课文抄下来（英文原样，中文照抄）。"
    return "", f"不认识 {ext} 这种文件。能打开就直接读；不行就请老师另存成 Word 或 PDF。"


def cmd_extract(a):
    parts, todo = [], []
    for f in a.files:
        p = Path(f).expanduser()
        if not p.is_file():
            todo.append(f"{f}：找不到这个文件")
            continue
        text, hint = extract(p)
        if hint:
            todo.append(f"{p.name}：{hint}")
            continue
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        parts.append(f"===== {p.name} =====\n{text}\n")
        print(f"  {p.name}：抽出 {len(text)} 个字符")
    if parts:
        out = Path(a.out).expanduser()
        out.write_text("\n".join(parts), encoding="utf-8")
        print(f"\n原文存在：{out}")
    for t in todo:
        print("  ⚠ " + t)
    if not parts and not todo:
        sys.exit("没给文件。")
    print("\n下一步：读原文，按 SKILL.md「拿到一课的资料，怎么转成词表」写出词表.md，"
          "再跑：python3 wordlist.py 查 词表.md")


# ── 查 ────────────────────────────────────────────
HAS_ZH = re.compile(r"[一-鿿]")
PLACEHOLDER = re.compile(r"\b(sb|sth|sw)\b\.?|…|\.\.\.|[/()（）\[\]]", re.I)


def check(text):
    """返回 (错误, 提醒, 统计)。错误 = 不改就会出错题；提醒 = 能跑但最好看一眼。"""
    errs, warns = [], []
    title, data = parse_wordlist(text)
    if not title:
        warns.append("没有「# 标题」，网页上会显示成「背课包」。第一行写 # Unit X 单元名。")

    # build_pack 会悄悄丢掉的行：在段落外面，或者少了 | 那一半
    sec = None
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("<!--"):
            continue
        if line.startswith("##"):
            key = line.lstrip("#").strip()
            sec = SECTIONS.get(key, SECTIONS.get(key[:1]))
            if not sec:
                sec = "?"
                errs.append(f"第 {n} 行「{line}」：只认 ## 词 / ## 句 / ## 错，这一段下面的都会被丢掉。")
            continue
        if line.startswith("#"):
            continue
        parts = [p for p in re.split(r"\s*[|｜]\s*", line) if p.strip()]
        if sec == "?":
            continue
        if sec is None:
            errs.append(f"第 {n} 行在任何 ## 段落前面，会被丢掉：{line[:40]}")
        elif len(parts) < 2:
            errs.append(f"第 {n} 行缺了 | 和另一半，会被丢掉：{line[:40]}")

    seen = {}
    for en, zh, *_ in data["word"]:
        k = en.lower()
        if k in seen:
            errs.append(f"「{en}」重复了。")
        seen[k] = 1
        if HAS_ZH.search(en) or not HAS_ZH.search(zh):
            errs.append(f"「{en} | {zh}」：要英文在左、中文在右。")
        if PLACEHOLDER.search(en):
            errs.append(f"「{en}」：学生要把左边整个拼出来，sb / sth / 省略号 / 斜杠 / 括号都拼不出来。"
                        f"改成学生真要写的样子，比如 devote oneself to sth. → devote oneself to。")
        if len(en.split()) > 5:
            warns.append(f"「{en}」有 {len(en.split())} 个词，像句子。句子放 ## 句。")

    heads = [w[0].split()[0].lower() for w in data["word"]]
    cloze = 0
    for en, zh, *_ in data["sentence"]:
        if not HAS_ZH.search(zh):
            errs.append(f"句子「{en[:30]}…」右边要写中文，学生是看中文默写英文。")
        if any(re.search(r"\b" + re.escape(h), en, re.I) for h in heads):
            cloze += 1
        if len(en.split()) > 25:
            warns.append(f"句子「{en[:30]}…」有 {len(en.split())} 个词，手机上默写太长，挑短一点的。")

    for row in data["fix"]:
        if len(row) < 3:
            errs.append(f"错句「{row[0][:30]}」少了第三列错因（{'／'.join(REASONS)}），"
                        f"不写会默认算「搭配」。")
            continue
        wrong, right, reason = row[0], row[1], row[2]
        if reason not in REASONS:
            errs.append(f"错句「{wrong[:30]}」的错因「{reason}」不在 {'／'.join(REASONS)} 里，"
                        f"学生怎么选都选不对。")
        if wrong.strip().lower() == right.strip().lower():
            errs.append(f"错句「{wrong[:30]}」左右一样，没有错可改。")

    nw, ns, nf = len(data["word"]), len(data["sentence"]), len(data["fix"])
    if nw == 0:
        errs.append("## 词 一个都没有，网页做不出来。")
    if ns and cloze == 0:
        warns.append("句子里一个词表里的词都没出现，情境填空关出不来。挑含有这些词的课文句子。")

    # 词表里放多少就考多少。估个时间给老师，让她自己决定要不要删
    stats = {"标题": title or "（无）", "词": nw, "句": ns, "错": nf,
             "闪认": nw, "情境填空": cloze, "造句": 1 if nw >= 2 else 0,
             "改错": nf, "默写": ns}
    secs = {"闪认": 15, "情境填空": 15, "造句": 90, "改错": 40, "默写": 60}
    stats["分钟"] = max(1, round(sum(stats[k] * v for k, v in secs.items()) / 60))
    return errs, warns, stats


def cmd_check(a):
    p = Path(a.file).expanduser()
    if not p.is_file():
        sys.exit("找不到词表：" + a.file)
    errs, warns, s = check(read_text(p))
    print(f"{s['标题']}：词 {s['词']} 个，句 {s['句']} 个，错句 {s['错']} 个。")
    levels = [f"{k} {s[k]} 题" for k in ("闪认", "情境填空", "造句", "改错", "默写") if s[k]]
    print(f"会出 {len(levels)} 关：" + "、".join(levels))
    print(f"学生大概要做 {s['分钟']} 分钟（粗估）。上次没背下来的词，发的时候还会再补最多 5 个。")
    for w in warns:
        print("  提醒：" + w)
    for e in errs:
        print("  错误：" + e)
    if errs:
        sys.exit(f"\n有 {len(errs)} 处错误，改完再查一次。")
    print("\n通过，可以发了。")


def main():
    ap = argparse.ArgumentParser(description="一课的资料 → 词表格式 → 检查")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("抽", help="把 Word/PDF/课件/文本里的文字抽出来")
    p.add_argument("files", nargs="+")
    p.add_argument("-o", dest="out", default="原文.txt")
    p.set_defaults(fn=cmd_extract)
    p = sub.add_parser("查", help="检查词表能不能直接发")
    p.add_argument("file")
    p.set_defaults(fn=cmd_check)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
