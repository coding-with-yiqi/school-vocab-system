#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""套在真 lark-cli 外面的一层：读飞书的调用原样交给真 lark-cli，写飞书的调用一律拦下。

live_check.py 用环境变量 LARK_CLI 把 beike.py 指到这里，所以验证时读到的是线上真数据，
但成绩表、单元表、词表、宠物账本和妙搭库一行都不会被改。

    REAL_LARK_CLI=<真 lark-cli>  READONLY_LOG=<记账文件>  readonly_lark.py <lark-cli 的参数…>

放行：子命令以 list / get / search / query 结尾的（+record-list、+table-list、+base-get…），
      以及 SQL 里没有 insert / update / delete / drop / create / alter / truncate 的 apps +db-execute。
拦下：其余一切（+record-batch-create、+record-batch-update、+table-create、写库的 +db-execute…）。
"""
import json, os, re, sys

REAL = os.environ["REAL_LARK_CLI"]
LOG = os.environ.get("READONLY_LOG")
args = sys.argv[1:]
sub = next((a for a in args if a.startswith("+")), "")
allow = bool(re.search(r"(list|get|search|query)$", sub))
if sub == "+db-execute":
    f = args[args.index("--file") + 1] if "--file" in args else ""
    sql = open(f, encoding="utf-8").read() if f and os.path.exists(f) else ""
    allow = bool(sql) and not re.search(r"\b(insert|update|delete|drop|create|alter|truncate)\b", sql, re.I)
if LOG:
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"放行" if allow else "拦下": " ".join(args[:1] + [sub])}, ensure_ascii=False) + "\n")
if allow:
    os.execv(REAL, [REAL] + args)
print(json.dumps({"ok": False, "error": {"message": "只读验证：这条会写飞书，已拦下"}}, ensure_ascii=False))
sys.exit(1)
