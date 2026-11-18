#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""找到本机的 lark-cli（老师自己登录的飞书命令行）。读写飞书、写妙搭库都经过它。

顺序：环境变量 LARK_CLI → PATH 里的 lark-cli → WorkBuddy 自带的那一份。
测试时把 LARK_CLI 指到 tests/readonly_lark.py，就只读不写。
"""
import os, shutil, sys

CLI_CANDIDATES = [
    os.environ.get("LARK_CLI", ""),
    shutil.which("lark-cli") or "",
    os.path.expanduser(
        "~/.workbuddy/binaries/node/cli-connector-packages/lib/node_modules"
        "/@larksuite/cli/bin/lark-cli"),
]


def find_cli():
    for c in CLI_CANDIDATES:
        if c and os.path.exists(c):
            return c
    sys.exit("找不到 lark-cli。装一个，或者用环境变量 LARK_CLI 指到它。")
