#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从飞书多维表格读回成绩 → 错题池

学生走表单提交的，成绩已经在表里，用这个脚本把"全班谁没背下来什么"算出来，
喂给下一个背课包的 --review。

只用标准库，不需要 pip install。

凭据从环境变量读，别写进文件：
    export FEISHU_APP_ID=cli_xxx
    export FEISHU_APP_SECRET=xxx

用法：
    python3 feishu_pull.py --app-token bascnXXXX --table tblXXXX --review 错题池.json
    python3 feishu_pull.py --app-token bascnXXXX --table tblXXXX --pack Unit-1-20261117 -o 成绩.csv

app-token 是多维表格链接里 /base/ 后面那一串；
table 是表格链接里 ?table= 后面那一串。
"""
import argparse, csv, json, os, re, sys, urllib.request, urllib.parse
from collections import Counter

BASE = "https://open.feishu.cn/open-apis"


def api(url, token=None, data=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method="POST" if body else "GET")
    req.add_header("Content-Type", "application/json; charset=utf-8")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            out = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        sys.exit(f"飞书接口报错 {e.code}：{e.read().decode()[:300]}")
    except urllib.error.URLError as e:
        sys.exit(f"连不上飞书：{e.reason}")
    if out.get("code"):
        sys.exit(f"飞书返回 code={out['code']}：{out.get('msg')}")
    return out


def token_of():
    app_id, secret = os.getenv("FEISHU_APP_ID"), os.getenv("FEISHU_APP_SECRET")
    if not app_id or not secret:
        sys.exit("先设置 FEISHU_APP_ID 和 FEISHU_APP_SECRET 环境变量。\n"
                 "在飞书开放平台建一个企业自建应用，开通多维表格读权限，"
                 "再把这个应用加进那张多维表格的协作者。")
    out = api(f"{BASE}/auth/v3/tenant_access_token/internal",
              data={"app_id": app_id, "app_secret": secret})
    return out["tenant_access_token"]


def records(token, app_token, table):
    rows, page = [], None
    while True:
        q = {"page_size": 500}
        if page:
            q["page_token"] = page
        out = api(f"{BASE}/bitable/v1/apps/{app_token}/tables/{table}/records"
                  f"?{urllib.parse.urlencode(q)}", token)
        d = out.get("data", {})
        rows += [r.get("fields", {}) for r in d.get("items", [])]
        page = d.get("page_token")
        if not d.get("has_more"):
            return rows


def flat(v):
    """多维表格的文本字段可能回来是 [{'text': '...'}] 这种结构。"""
    if isinstance(v, list):
        return "".join(x.get("text", "") if isinstance(x, dict) else str(x) for x in v)
    if isinstance(v, dict):
        return v.get("text", "") or str(v)
    return "" if v is None else str(v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app-token", required=True)
    ap.add_argument("--table", required=True)
    ap.add_argument("--pack", help="只看某个内容包")
    ap.add_argument("-o", "--out", help="导出成绩 csv")
    ap.add_argument("--review", help="写出错题池 json")
    a = ap.parse_args()

    rows = [{k: flat(v) for k, v in r.items()} for r in records(token_of(), a.app_token, a.table)]
    if a.pack:
        rows = [r for r in rows if a.pack in r.get("内容包", "")]
    if not rows:
        sys.exit("表里没读到记录。检查 app-token / table 对不对，应用有没有加进协作者。")
    print(f"✓ 读到 {len(rows)} 条记录")

    # 多次尝试全留。第一次才反映真实掌握，这里按「第几次」去重同一条重复写入。
    last = {}
    for r in rows:
        last[(r.get("班级", ""), r.get("姓名", ""), r.get("内容包", ""), r.get("第几次", ""))] = r
    rows = list(last.values())
    print(f"  去重后 {len(rows)} 条提交（同一人同一包的不同次数都保留）")

    # 「还不会」比「差一点」更该优先：记 2 分 / 1 分
    weight, people = Counter(), Counter()
    for r in rows:
        for w in re.split(r"[、,]", r.get("还不会清单", "")):
            if w.strip():
                weight[w.strip()] += 2
                people[w.strip()] += 1
        for w in re.split(r"[、,]", r.get("差一点清单", "")):
            if w.strip():
                weight[w.strip()] += 1
                people[w.strip()] += 1

    要看 = [r.get("姓名") for r in rows
            if r.get("待老师看") or r.get("自评") == "我还不会" or r.get("用时偏短")]
    if 要看:
        print(f"\n  要你亲自看的：{'、'.join(filter(None, 要看))}")
    if weight:
        print("\n  全班最没拿下的：")
        for w, _ in weight.most_common(10):
            print(f"    {people[w]} 人　{w}")

    if a.out:
        keys = ["班级", "姓名", "内容包", "第几次", "对了", "差一点", "还不会",
                "待老师看", "自评", "用时秒", "用时偏短", "还不会清单", "差一点清单"]
        with open(a.out, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        print(f"\n✓ {a.out}")
    if a.review:
        pool = [w for w, _ in weight.most_common() if re.fullmatch(r"[A-Za-z][A-Za-z ]*", w)]
        with open(a.review, "w", encoding="utf-8") as f:
            json.dump(pool, f, ensure_ascii=False, indent=2)
        print(f"✓ {a.review}　{len(pool)} 个词会排进下一个背课包的最前面")


if __name__ == "__main__":
    main()
