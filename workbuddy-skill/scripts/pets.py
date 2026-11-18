# -*- coding: utf-8 -*-
"""养宠：每个学生一颗蛋（孵出 11 种小动物之一），用真成绩算豆子 → 孵化、长大；豆子还能在小卖部换配饰。不连网、不碰凭证。

    compute(看板模型, 状态, 学期, 上次) → 每个班每个人的宠物 + 小卖部 + 班级目标
    render_html(宠物模型, 模板, 图片网址, 开店信息) → 宠物墙网页（图片按相对路径引用，没有的用占位画）

口径（详见 04_工程/养宠系统设计.md）：
- 每个单元单独算，看最近一次提交：
  分数豆 = 对了 ÷ (题数 − 造句题) × 6，四舍五入（满分 6）；交了 +2；重做后「对了」变多 +2；
  造句写了 +1；全班交到九成每人 +2。期末那种按人出词的课，题数按每人自己的算。
- 「我的复习」：每交一轮 +2（偏短的不算）；错过的词拿下了（learning.py 的口径：连续两次第一遍就对）每个 +1。
- 「用时偏短」的那次不算豆子（也不扣）。没交不扣，宠物不会走。
- 长大看「一共挣了多少」，花掉的豆子不影响长大；能花的 = 挣的 − 换配饰花掉的。
- 班级目标：全班人均挣到 15 / 40 / 80 颗，解锁草地 / 温泉 / 星空，全班宠物一起换背景。
- 每次从成绩表从头算。手写的状态只有 ~/.beike/宠物/ 下的几个小文件：送的.json（老师送的）、
  换的.json（学生拿豆子换的）、穿戴.json（学生选戴哪件）、装备.json（每单元的装备词）。
"""
import hashlib, html, json, re
from datetime import datetime
from pathlib import Path

# 11 种小动物：物种、英文名（也是图片文件名）、小名、主色、外观（给 Codex 生成图片用）
SPECIES = [
    ("卡皮巴拉", "Capy", "卡皮", "#c8925f", "a capybara: chubby barrel-shaped body, warm caramel-brown fur, tiny round ears, big calm nose, sleepy chill half-closed eyes, a small yuzu-colored blush"),
    ("羊驼", "Alpaca", "驼驼", "#f3e6cf", "an alpaca: fluffy cream-white wool like a cloud, long fluffy neck, a big fluffy fringe on top of the head, banana-shaped little ears, gentle smile"),
    ("猫", "Cat", "喵喵", "#f2b06b", "a cat: round orange-and-cream tabby kitten with soft stripes on the forehead, pointy ears with pink insides, curled tail, content cat smile"),
    ("柴犬", "Shiba", "柴柴", "#e9a15a", "a shiba inu dog: tan-orange fur with a white face mask and white tummy, small pointed ears, curly tail, happy open smile"),
    ("小黄鸭", "Duck", "鸭鸭", "#ffd84d", "a duckling: round bright-yellow fluffy chick-duck, small orange beak, tiny orange feet, a little tuft of feathers on top"),
    ("兔子", "Bunny", "兔兔", "#f6c9d6", "a bunny: round white-and-pink rabbit, long floppy ears with pink insides, pink nose, puffy cotton tail"),
    ("仓鼠", "Hamster", "团团", "#f0c08a", "a hamster: very round golden-cream hamster with stuffed puffy cheeks, tiny round ears, tiny paws held at the chest"),
    ("熊猫", "Panda", "滚滚", "#4a4a4a", "a giant panda: round white body with black ears, black eye patches, black arms and legs, sleepy happy face"),
    ("企鹅", "Penguin", "啾啾", "#5b8fd6", "a penguin: round soft-blue-and-white baby penguin, small orange beak, little flippers, waddly orange feet"),
    ("水獭", "Otter", "獭獭", "#a87a55", "an otter: soft brown otter with a cream face and whiskers, small round ears, holding paws together, thick tail"),
    ("小狐狸", "Fox", "橘橘", "#ef8a4a", "a fox: little orange fox with white cheeks and chest, big pointy ears, fluffy tail with a white tip"),
]
STAGES = [(0, "蛋"), (8, "宝宝"), (30, "少年"), (80, "完全体")]
SLOT_ZH = {"head": "头上", "hand": "手里", "side": "身边"}
SLOTS = {"头": "head", "手": "hand", "身边": "side"}
PRICE = {"head": 8, "hand": 6, "side": 10}

# 小卖部常驻的配饰（单元装备另外加）
SHOP_BASE = [
    ("head", "sun hat", "遮阳帽"), ("head", "headphones", "耳机"), ("head", "flower crown", "花环"),
    ("head", "yuzu", "柚子"), ("head", "beret", "贝雷帽"), ("head", "graduation cap", "学士帽"),
    ("hand", "pencil", "铅笔"), ("hand", "book", "书"), ("hand", "boba tea", "珍珠奶茶"),
    ("hand", "balloon", "气球"), ("hand", "umbrella", "雨伞"), ("hand", "magnifying glass", "放大镜"),
    ("side", "potted plant", "盆栽"), ("side", "kite", "风筝"), ("side", "rubber duck", "小黄鸭"),
    ("side", "cushion", "坐垫"), ("side", "globe", "地球仪"), ("side", "backpack", "书包"),
]
# 每一课自动上架的三件（头 / 手 / 身边），图都提前画好了。老师用「宠物 装备」指定了的，按老师的。
# 课本单元按标题认（人教版选择性必修一）；认不出的课，按第几课轮流用 GENERIC_KIT。
UNIT_KIT = {
    "people of achievement": [("头", "laurel wreath", "桂冠"), ("手", "gold medal", "金牌"), ("身边", "microscope", "显微镜")],
    "looking into the future": [("头", "VR goggles", "VR 眼镜"), ("手", "glowing tablet", "发光平板"), ("身边", "little robot", "小机器人")],
    "fascinating parks": [("头", "explorer hat", "探险帽"), ("手", "binoculars", "望远镜"), ("身边", "tent", "帐篷")],
    "body language": [("头", "heart sunglasses", "爱心墨镜"), ("手", "foam cheering hand", "加油手套"), ("身边", "speech bubble sign", "对话气泡牌")],
    "working the land": [("头", "straw farmer hat", "农夫草帽"), ("手", "watering can", "洒水壶"), ("身边", "vegetable basket", "菜篮子")],
}
GENERIC_KIT = [
    [("头", "bunny-ear headband", "兔耳发箍"), ("手", "ice cream cone", "冰淇淋"), ("身边", "telescope", "天文望远镜")],
    [("头", "knit beanie", "毛线帽"), ("手", "paintbrush", "画笔"), ("身边", "little guitar", "小吉他")],
    [("头", "little crown", "小皇冠"), ("手", "microphone", "麦克风"), ("身边", "skateboard", "滑板")],
    [("头", "party hat", "派对帽"), ("手", "lollipop", "棒棒糖"), ("身边", "little snowman", "小雪人")],
    [("头", "chef hat", "厨师帽"), ("手", "fishing rod", "钓鱼竿"), ("身边", "pumpkin lantern", "南瓜灯")],
    [("头", "sailor hat", "水手帽"), ("手", "magic wand", "魔法棒"), ("身边", "little bicycle", "小自行车")],
]


def default_items(u, i):
    """这一课没指定装备时自动上架的三件：课本单元的主题装备，认不出就按顺序轮流用通用的。"""
    t = str(u.get("title") or "").lower()
    kit = next((v for k, v in UNIT_KIT.items() if k in t), None) or GENERIC_KIT[(u.get("lesson") or i + 1) % len(GENERIC_KIT) - 1]
    return [{"slot": a, "en": b, "zh": c} for a, b, c in kit]


def all_kit_items():
    return [x for kit in list(UNIT_KIT.values()) + GENERIC_KIT for x in kit]


# 老师可以送的（不卖）
GIFTS = {
    "金色围巾": ("side", "golden scarf"), "小红花": ("head", "red flower"), "星星发卡": ("head", "star clip"),
    "彩虹披风": ("side", "rainbow cape"), "小喇叭": ("hand", "trumpet"), "奖杯": ("hand", "trophy"),
}
GIFT_BEANS = 3
# 班级目标：人均挣到多少颗，全班解锁一个背景
SCENES = [(15, "meadow", "草地"), (40, "hot spring", "温泉"), (80, "starry night", "星空")]


def unit_label(u):
    """有课目录时叫「第 N 课」（和学生页一致），没有就叫 Unit N。"""
    return f"第{u['lesson']}课" if u.get("lesson") else re.sub(r"^(Unit \d+).*", r"\1", u["title"])


def species_of(cls, name, term):
    return hashlib.sha256(f"{cls}·{name}·{term}".encode()).digest()[0] % len(SPECIES)


def stage_of(earned):
    i = max(i for i, (t, _) in enumerate(STAGES) if earned >= t)
    return i, (STAGES[i + 1][0] if i + 1 < len(STAGES) else None)


def slug(en):
    return re.sub(r"[^a-z0-9]+", "-", en.lower()).strip("-")


def catalog(model, items_cfg):
    """小卖部：常驻的 + 每个已发单元的装备（单元装备比常驻的贵 2 颗）。"""
    out, seen = [], set()
    for slot, en, zh in SHOP_BASE:
        out.append({"id": slug(en), "slot": slot, "en": en, "zh": zh, "price": PRICE[slot], "unit": ""})
        seen.add(slug(en))
    for ui, u in enumerate(model["units"]):
        for x in items_cfg.get(u["id"]) or default_items(u, ui):
            i = slug(x["en"])
            if i in seen:
                continue
            seen.add(i)
            slot = SLOTS.get(x.get("slot", "头"), "side")
            out.append({"id": i, "slot": slot, "en": x["en"], "zh": x.get("zh", ""), "price": PRICE[slot] + 2,
                        "unit": unit_label(u)})
    return out


def unit_base(s, u):
    """算分数豆的分母：正课按这一课的题数；期末每人的词不一样，按这个人自己交上来的题数。"""
    if u["n"] and not u.get("per_person"):
        return max(1, u["n"] - s["counts"][3])
    return max(1, s["sum"] - s["counts"][3])


def unit_beans(s, u, goal):
    """一个学生在一个单元挣的豆子：[(为什么, 几颗)]。"""
    real = s["tries"] > len(s["fast"])
    if not real:
        return [("这次做得太快，没算豆子", 0)], False
    got = [("交了", 2)]
    base = unit_base(s, u)
    sc = round(6 * min(1, s["counts"][0] / base))
    if sc:
        got.append((f"对了 {s['counts'][0]}/{base} 题", sc))
    if s["tries"] > 1 and s["last_right"] > s["first_right"] and not s.get("last_fast"):
        got.append(("重做后对的变多了", 2))
    if s["counts"][3] > 0:
        got.append(("造句写了", 1))
    if goal:
        got.append(("全班交到九成", 2))
    return got, True


def can_still(s, u):
    """最新单元还能多拿几颗（给学生看的「再努力一下」）。"""
    if not s["done"]:
        return 2 + 6 + 1, "交了这单元最多还能拿约 9 颗"
    base = unit_base(s, u)
    now = round(6 * min(1, s["counts"][0] / base))
    more = (6 - now) + (0 if s["tries"] > 1 and s["last_right"] > s["first_right"] else 2)
    if s["tries"] <= len(s["fast"]):
        return 2 + 6, "认真再做一次，能拿约 8 颗"
    return (more, f"再做一次、对得更多，还能拿 {more} 颗") if more > 0 else (0, "这单元的豆子都拿满了")


def compute(model, state=None, term="", last=None, items_cfg=None):
    state = state or {}
    items_cfg, last = items_cfg or state.get("装备", {}), last or {}
    no_roster = model["meta"].get("no_roster")
    units = model["units"]
    shop = catalog(model, items_cfg)
    shop_by = {x["id"]: x for x in shop}
    shown = [i for i, u in enumerate(units) if not u.get("hidden")]
    last_i = shown[-1] if shown else len(units) - 1                    # 学生页上最新的一课：「在等你交」看它
    done_i = next((i for i in reversed(shown) if any(c["done"] for c in units[i]["classes"])), last_i)  # 九成目标看最近有人交的

    pets = {}
    for c in model["classes"]:
        for u in units:
            for s in u["students"]:
                if s["cls"] == c and not s.get("unknown"):
                    pets.setdefault((c, s["name"]), {"cls": c, "name": s["name"], "earned": 0, "spent": 0,
                                                     "log": [], "own": [], "waiting": "", "can": [0, ""]})

    for ui, u in enumerate(units):
        short = unit_label(u)
        goal = {cc["cls"]: bool(not no_roster and cc["total"] and cc["done"] >= 0.9 * cc["total"]) for cc in u["classes"]}
        for s in u["students"]:
            p = pets.get((s["cls"], s["name"]))
            if not p:
                continue
            if ui == last_i:
                p["can"] = list(can_still(s, u))
            if not s["done"]:
                if ui == last_i:
                    p["waiting"] = short
                continue
            got, _ = unit_beans(s, u, goal.get(s["cls"]))
            p["earned"] += sum(b for _, b in got)
            p["log"].append({"unit": short, "got": [{"why": w, "n": b} for w, b in got]})

    for (c, n), p in pets.items():
        key, got = f"{c}·{n}", []
        rounds = len(model.get("reviews", {}).get(key, []))
        if rounds:
            got.append((f"做了 {rounds} 轮「我的复习」", 2 * rounds))
        mastered = ((model.get("learn") or {}).get(key) or {}).get("got") or []
        if mastered:
            got.append((f"复习拿下了 {len(mastered)} 个词：{'、'.join(mastered[:5])}{'…' if len(mastered) > 5 else ''}",
                        len(mastered)))
        if got:
            p["earned"] += sum(b for _, b in got)
            p["log"].append({"unit": "我的复习", "got": [{"why": w, "n": b} for w, b in got]})

    for g in state.get("送", []):
        p = pets.get((g.get("cls", ""), g.get("name", "")))
        if not p or g.get("item") not in GIFTS:
            continue
        slot, en = GIFTS[g["item"]]
        p["own"].append({"id": slug(en), "slot": slot, "en": en, "zh": g["item"], "from": "老师送的",
                         "reason": g.get("reason", ""), "date": g.get("date", "")})
        p["earned"] += GIFT_BEANS
        p["log"].append({"unit": "老师送的", "got": [{"why": g["item"] + (f"（{g['reason']}）" if g.get("reason") else ""),
                                                   "n": GIFT_BEANS}]})
    for b in state.get("换", []):
        p, it = pets.get((b.get("cls", ""), b.get("name", ""))), shop_by.get(b.get("id"))
        if not p or not it:
            continue
        p["own"].append({**it, "from": "自己换的", "paid": b.get("price", it["price"]), "date": b.get("date", "")})
        p["spent"] += b.get("price", it["price"])

    out, changes = [], {"hatched": [], "grew": []}
    wear_cfg = state.get("戴", {})
    for k, p in pets.items():
        st, nxt = stage_of(p["earned"])
        key = f"{k[0]}·{k[1]}"
        before = last.get(key)
        p.update({"sp": species_of(k[0], k[1], term), "stage": st, "next": nxt, "key": key,
                  "balance": p["earned"] - p["spent"],
                  "new": "" if before is None or before >= st else ("hatched" if before == 0 else "grew")})
        if p["new"]:
            changes["hatched" if p["new"] == "hatched" else "grew"].append(key)
        owned = {it["id"]: it for it in p["own"]}
        wear = {}
        for it in p["own"]:                              # 默认戴每个位置最新的那件
            wear[it["slot"]] = it["id"]
        for slot, iid in wear_cfg.get(key, {}).items():   # 学生自己选过的优先；选了「不戴」就是空
            if iid == "" or iid in owned:
                wear[slot] = iid
        p["wear"] = {s: i for s, i in wear.items() if i}
        out.append(p)

    goals, scenes = [], {}
    for c in model["classes"]:
        ps = [p for p in out if p["cls"] == c]
        avg = sum(p["earned"] for p in ps) / max(1, len(ps))
        got = [sc for sc in SCENES if avg >= sc[0]]
        nxt = next((sc for sc in SCENES if avg < sc[0]), None)
        scenes[c] = {"avg": round(avg, 1), "have": [{"id": slug(e), "en": e, "zh": z} for _, e, z in got],
                     "next": {"at": nxt[0], "zh": nxt[2], "need": round(nxt[0] * len(ps) - sum(p["earned"] for p in ps))} if nxt else None}
        if units and not no_roster:
            cc = next((x for x in units[done_i]["classes"] if x["cls"] == c), None)
            if cc:
                goals.append({"cls": c, "done": cc["done"], "total": cc["total"], "need": -(-9 * cc["total"] // 10),
                              "unit": unit_label(units[done_i])})
    return {"meta": {**model["meta"], "term": term,
                     "generated": model["meta"].get("generated") or datetime.now().strftime("%Y-%m-%d %H:%M")},
            "classes": model["classes"], "pets": out, "changes": changes, "goals": goals, "scenes": scenes,
            "shop": shop, "species": [{"kind": a, "en": b, "zh": c, "color": d} for a, b, c, d, _ in SPECIES],
            "stages": [n for _, n in STAGES], "thresholds": [t for t, _ in STAGES],
            "scene_rules": [{"at": a, "en": e, "zh": z} for a, e, z in SCENES], "first_run": not last}


# ── 换配饰（开店模式下网页调这里；命令行也能用）──────────────
def buy(pm, state, key, iid, today):
    p = next((x for x in pm["pets"] if x["key"] == key), None)
    it = next((x for x in pm["shop"] if x["id"] == iid), None)
    if not p or not it:
        return "找不到这个学生或这件配饰。"
    if p["stage"] == 0:
        return "蛋还没孵出来，孵出来以后才能换配饰。"
    if any(o["id"] == iid for o in p["own"]):
        return "已经有这件了。"
    if p["balance"] < it["price"]:
        return f"豆子不够：要 {it['price']} 颗，现在有 {p['balance']} 颗。"
    cls, name = key.split("·", 1)
    state.setdefault("换", []).append({"cls": cls, "name": name, "id": iid, "price": it["price"], "date": today})
    state.setdefault("戴", {}).setdefault(key, {})[it["slot"]] = iid
    return ""


def refund(state, key, iid):
    cls, name = key.split("·", 1)
    xs = state.get("换", [])
    for i in range(len(xs) - 1, -1, -1):
        if xs[i].get("cls") == cls and xs[i].get("name") == name and xs[i].get("id") == iid:
            xs.pop(i)
            w = state.get("戴", {}).get(key, {})
            for s in [s for s, v in w.items() if v == iid]:
                w.pop(s)
            return ""
    return "没有换过这件，退不了（老师送的不能退）。"


def wear(pm, state, key, slot, iid):
    p = next((x for x in pm["pets"] if x["key"] == key), None)
    if not p or slot not in SLOT_ZH:
        return "找不到。"
    if iid and not any(o["id"] == iid and o["slot"] == slot for o in p["own"]):
        return "还没有这件。"
    state.setdefault("戴", {}).setdefault(key, {})[slot] = iid
    return ""


def snapshot(pm):
    return {p["key"]: p["stage"] for p in pm["pets"]}


def change_text(pm):
    if pm["first_run"]:
        n = sum(1 for p in pm["pets"] if p["stage"] > 0)
        return f"第一次生成宠物墙：{len(pm['pets'])} 颗蛋，已经孵出来 {n} 只。"
    h, g = pm["changes"]["hatched"], pm["changes"]["grew"]
    if not h and not g:
        return "和上次比，没有新孵出来或长大的。"
    f = lambda xs: "、".join(x.replace("高一", "") for x in xs[:12]) + ("…" if len(xs) > 12 else "")
    return "；".join(([f"新孵出来 {len(h)} 只：{f(h)}"] if h else []) + ([f"长大了 {len(g)} 只：{f(g)}"] if g else [])) + "。"


# ── 图片 ─────────────────────────────────────────────
def pet_files():
    out = []
    for _, en, _, _, _ in SPECIES:
        out += [f"egg-{en.lower()}.png"] + [f"{en.lower()}-{st}.png" for st in ("baby", "teen", "adult")]
    return out


def item_files(pm):
    ids = {x["id"] for x in pm["shop"]} | {slug(en) for _, en in GIFTS.values()}
    return [f"item-{i}.png" for i in sorted(ids)] + [f"scene-{slug(e)}.png" for _, e, _ in SCENES]


def image_urls(pm, img_dir, prefix):
    """图片目录里有的图 → {文件名: 网址}。网页按相对路径引用，不内嵌（一张不少于几十 KB，内嵌会让网页变成几 MB）。"""
    d = Path(img_dir) if img_dir else None
    if not d or not d.is_dir():
        return {}
    return {f: prefix + f for f in pet_files() + item_files(pm) if (d / f).is_file()}


def render_html(pm, template, images=None, live=None):
    pm = dict(pm, images=images or {}, live=live or None)
    data = json.dumps(pm, ensure_ascii=False).replace("</", "<\\/")
    title = "宠物墙" + ("（演示数据）" if pm["meta"].get("demo") else "")
    return template.replace("{{TITLE}}", html.escape(title)).replace("{{DATA}}", data)


STYLE = ("Original cute chibi animal comic sticker style (the same style as a cute chill capybara comic sticker): "
         "chubby round body, very simple shapes, bold dark-brown rounded outline, soft pastel flat colors with tiny soft "
         "shading, small dot eyes or calm sleepy closed eyes, rosy cheeks, tiny limbs. Thick white sticker border around "
         "the whole subject. Single subject centered, front view sitting, subject fills about 70% of a square 1024x1024 "
         "canvas, head in the upper-middle, feet near the bottom. No text, no letters, no watermark, no frame, no scenery.")
ITEM_STYLE = ("Same cute animal-comic sticker style: bold dark-brown rounded outline, soft pastel flat colors, "
              "thick white sticker border. A single object alone, no animal, centered, front view, fills about 70% "
              "of a square 1024x1024 canvas. No text, no letters, no watermark, no scenery.")


def image_jobs(pm):
    """每张图：文件名 + 英文描述。给 Codex Image 用，也写进图片清单。"""
    jobs = []
    for kind, en, zh, color, desc in SPECIES:
        e = en.lower()
        jobs.append((f"egg-{e}.png", f"{STYLE} Subject: a smooth round egg (no animal visible) in cream white with soft spots in {color}, "
                     f"a tiny crack at the top, and one small hint of what is inside drawn as a pattern on the shell (from: {desc})."))
        jobs.append((f"{e}-baby.png", f"{STYLE} Subject: a tiny baby version, very small and round with big cheeks: {desc}."))
        jobs.append((f"{e}-teen.png", f"{STYLE} Subject: the same character a bit older, a bit taller and more confident: {desc}."))
        jobs.append((f"{e}-adult.png", f"{STYLE} Subject: the same character fully grown, big and chunky, proud relaxed pose, a few tiny sparkles around: {desc}."))
    seen = set()
    for en in [it["en"] for it in pm["shop"]] + [b for _, b, _ in all_kit_items()]:
        if slug(en) not in seen:
            seen.add(slug(en))
            jobs.append((f"item-{slug(en)}.png", f"{ITEM_STYLE} Subject: a single {en}."))
    for _, en in GIFTS.values():
        jobs.append((f"item-{slug(en)}.png", f"{ITEM_STYLE} Subject: a single {en}, a little shiny and special."))
    for _, en, zh in SCENES:
        jobs.append((f"scene-{slug(en)}.png", "Soft pastel cute capybara-comic style background scene, no animals, no text, "
                     f"wide flat landscape, gentle colors, simple shapes: a {en}. Square 1024x1024, full bleed, no sticker border."))
    return jobs


def prompts_md(pm):
    lines = ["# 宠物图片清单（给 Codex Image 用）", "",
             "画好的图放进 `~/.beike/宠物/图/`，文件名照下面写。下次「宠物」会自动换上。",
             "宠物和配饰要透明背景（做不到就用纯绿 #00FF00 背景，脚本会抠掉）；背景图（scene-）不用透明。", ""]
    for f, prompt in image_jobs(pm):
        lines += [f"## `{f}`", "", prompt, ""]
    return "\n".join(lines)
