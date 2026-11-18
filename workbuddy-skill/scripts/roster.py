# -*- coding: utf-8 -*-
"""名单文件怎么读。publish.py 和 collect.py 共用，两边读出来必须一模一样，
不然「网页里能选的人」和「算谁没交时的人」对不上。

一个文件可以装好几个班，两种写法随便混：

    # 从学校系统导出的两列，直接粘
    王小明,高一3班
    李思远,高一3班

    # 或者一个班一段，段头写班级
    ## 高一4班
    陈默
    赵一诺

`#` 开头（后面不是第二个 #）是注释。分隔符认英文逗号、中文逗号、Tab。
"""
import re
from collections import OrderedDict
from pathlib import Path


def read(paths, default_cls=""):
    """返回 OrderedDict{班级: [姓名, ...]}，班级按第一次出现的顺序。

    paths 可以是一个路径，也可以是好几个。只有一列、又没在任何段头底下的名字，
    用 default_cls（也就是 --class）当班级。
    """
    if isinstance(paths, (str, Path)):
        paths = [paths]
    out = OrderedDict()
    for p in paths:
        cur = default_cls
        for raw in Path(p).read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith("##"):
                cur = line.lstrip("#").strip()
                continue
            if line.startswith("#"):
                continue
            parts = [x.strip() for x in re.split(r"[,\t，]", line) if x.strip()]
            if not parts:
                continue
            name = parts[0]
            cls = parts[1] if len(parts) > 1 else cur
            names = out.setdefault(cls, [])
            if name not in names:
                names.append(name)
    return out
