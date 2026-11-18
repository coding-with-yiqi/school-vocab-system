# -*- coding: utf-8 -*-
"""学生页、成绩表、BK2 结果码三处共用的字段约定，只在这里写一份。

一次作答从学生页出来有两条路，最后都落成成绩表里的一行：
    学生页 payload()    ──表单预填 prefill_<列名>──▶ 成绩表（列 = SCORE_COLUMNS）
    学生页 resultCode() ──「BK2|…」发群里──▶ beike.py 收 / collect.py ──▶ 同一张成绩表
成绩表的一行也能按 BK2_ORDER 还原成一串结果码，所以两条路走同一套统计。

学生页那头（workbuddy-skill/assets/student.html）的 payload() 键、resultCode() 顺序、
shortOf() 标签和这里对不上时，tests/contracts.py 会报出来。改这里就要跑它。

明细的写法：「题号:结果,题号:结果,…」，按关卡顺序；结果是 DETAIL 里的四个词之一。
还不会清单 / 差一点清单：shortOf(题号) 的标签，用「、」连。
"""

# 成绩表的列。建表、表单可见字段、往表里写，都按这个顺序。
SCORE_COLUMNS = ["姓名", "班级", "内容包", "第几次", "对了", "差一点", "还不会", "待老师看",
                 "还不会清单", "差一点清单", "造句原文", "自评", "用时秒", "用时偏短", "明细"]
# 其中是数字的列（建表时建成数字列；写表时转成整数）
SCORE_NUMS = {"第几次", "对了", "差一点", "还不会", "待老师看", "用时秒"}

# BK2 结果码「BK2|a|b|…」里各段的顺序 = 学生页 resultCode()。不含造句原文（太长，也可能有竖线）。
BK2_ORDER = ["班级", "姓名", "内容包", "第几次", "对了", "差一点", "还不会", "待老师看",
             "自评", "用时秒", "用时偏短", "还不会清单", "差一点清单", "明细"]

# 学生页 payload() 的键 → 成绩表的列（表单预填用）
WEB_TO_COLUMN = {"cls": "班级", "student": "姓名", "packId": "内容包", "attempt": "第几次", "right": "对了",
                 "shaky": "差一点", "nope": "还不会", "toTeacher": "待老师看", "nopeList": "还不会清单",
                 "shakyList": "差一点清单", "composeText": "造句原文", "selfRating": "自评",
                 "durationSec": "用时秒", "tooFast": "用时偏短", "detail": "明细"}

# 明细里每题的结果 → 它算进哪个数
DETAIL = {"pass": "对了", "near": "差一点", "fail": "还不会", "review": "待老师看"}
