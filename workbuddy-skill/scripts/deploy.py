#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 publish.py 生成的网页发布成学生能点开的链接（飞书托管）。

    python3 deploy.py 高一_U1.html

几个班装在同一个网页里，所以只发布一次、只有一个链接，发到每个班群。
默认应用名「背单词闯关」：以后每次发新单元都更新这同一个应用，链接永远不变 ——
班群里置顶那条链接一学期都有效，学生点开就是当前这一单元。

实测结论（2026-11-17）：
  - 新建的 html 应用默认只有「组织内」能看（tenant_readable），
    学生打开是「没有访问权限」。所以每次发布完都要把分享设成
    「互联网上获得链接的任何人可阅读」，这一步脚本自己做，还会回读确认。
  - `apps +access-scope-set` 报「创意模式应用不支持设置可用范围」，
    跟这件事无关 —— html 应用的访问权限归云文档管。别去碰它。
  - 页面在飞书外壳的跨域 iframe 里，外层链接的 ?c= 之类参数传不进去。
    所以不能靠链接分班，班级跟着学生选的名字走。
  - 微信不拦 feishu.cn 链接，未登录的手机能直接打开。
"""
import argparse, json, os, shutil, subprocess, sys, tempfile, time
from pathlib import Path

CLI_CANDIDATES = [
    os.environ.get("LARK_CLI", ""),
    shutil.which("lark-cli") or "",
    os.path.expanduser(
        "~/.workbuddy/binaries/node/cli-connector-packages/lib/node_modules"
        "/@larksuite/cli/bin/lark-cli"),
]
# 应用名 → app_id。不靠按名字搜：飞书的 --keyword 带空格就搜不到，
# 刚建的应用也要过一会儿才进索引。搜不到就会再建一个，链接就变了。
STATE = Path(os.path.expanduser("~/.beike/apps.json"))
START, END = "/*__PACK_START__*/", "/*__PACK_END__*/"


def find_cli():
    for c in CLI_CANDIDATES:
        if c and os.path.exists(c):
            return c
    sys.exit("找不到 lark-cli。装一个，或者用环境变量 LARK_CLI 指到它。")


def run(cli, *args, ok_codes=()):
    """跑一条 lark-cli，返回 data；失败把飞书的原话打出来再退出。"""
    p = subprocess.run([cli, *args, "--as", "user", "--format", "json"],
                       capture_output=True, text=True)
    out = None
    for raw in (p.stdout, p.stderr):          # 报错时 lark-cli 走 stderr
        if (raw or "").strip():
            try:
                out = json.loads(raw)
                break
            except Exception:
                pass
    if out is None:
        sys.exit("lark-cli 没返回 JSON：\n" + (p.stdout or p.stderr or "")[:800])
    if not out.get("ok"):
        err = out.get("error") or {}
        if err.get("code") in ok_codes:
            return None
        sys.exit("飞书拒绝了这一步：%s\n命令：lark-cli %s" %
                 (err.get("message") or json.dumps(err, ensure_ascii=False),
                  " ".join(args[:2])))
    return out.get("data") or {}


def load_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(st):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def find_app(cli, name):
    """先查本机记下的 app_id；没有再把自己的 html 应用全翻一遍，按名字精确对。"""
    st = load_state()
    if name in st:
        d = run(cli, "apps", "+get", "--app-id", st[name])
        app = (d or {}).get("app")
        if app and app.get("app_type") == "html":
            return app
    # 不加 --app-type html：lark-cli 1.0.98 上这个筛选是坏的，只返回全栈应用，
    # 「背单词闯关」反而不在里面（2026-11-17 实测），结果会再建一个、链接就变了。
    # 改成全翻一遍，自己按 app_type 和名字精确对。
    token = ""
    while True:
        args = ["apps", "+list", "--ownership", "mine", "--page-size", "50"]
        if token:
            args += ["--page-token", token]
        d = run(cli, *args)
        for it in d.get("items", []):
            if it.get("name") == name and it.get("app_type") == "html":
                st[name] = it["app_id"]
                save_state(st)
                return it
        token = d.get("page_token") or ""
        if not d.get("has_more") or not token:
            return None


def make_public(cli, meta_token):
    """设成「互联网上获得链接的任何人可阅读」，再读回来确认真的生效了。"""
    path = f"/open-apis/drive/v2/permissions/{meta_token}/public"
    params = json.dumps({"type": "apps"})
    run(cli, "api", "PATCH", path, "--params", params, "--data", json.dumps(
        {"external_access_entity": "open", "link_share_entity": "anyone_readable"}))
    pp = run(cli, "api", "GET", path, "--params", params).get("permission_public", {})
    if pp.get("link_share_entity") != "anyone_readable" or \
            pp.get("external_access_entity") != "open":
        sys.exit("设公开没生效，学生会打不开。现在的设置是：\n  " +
                 json.dumps(pp, ensure_ascii=False) +
                 "\n可能是你们组织的管理员关了「对外分享」，要去飞书管理后台打开。")


def read_pack(html_path):
    try:
        s = Path(html_path).read_text(encoding="utf-8")
        return json.loads(s.split(START, 1)[1].split(END, 1)[0])
    except Exception:
        return {}


def publish(html, name="背单词闯关", timeout=180):
    """发布并设成公开，返回链接。beike.py 也调这个。"""
    args = argparse.Namespace(html=html, name=name, timeout=timeout)
    if not os.path.isfile(args.html):
        sys.exit("找不到这个文件：" + args.html)
    cli = find_cli()

    app = find_app(cli, args.name)
    if app:
        app_id = app["app_id"]
        print(f"更新已有应用「{args.name}」，链接不变")
    else:
        app_id = run(cli, "apps", "+create", "--name", args.name,
                     "--app-type", "html",
                     "--description", "背单词闯关学生端")["app"]["app_id"]
        # 建完马上记下来：后面哪一步失败了，下次重跑也会复用它，不会再建一个
        st = load_state(); st[args.name] = app_id; save_state(st)
        print(f"新建应用「{args.name}」")

    # 入口必须叫 index.html。lark-cli 的 --path 只收当前目录、/tmp、~/files，
    # 系统默认临时目录（/var/folders/...）会被拒，所以临时目录建在当前目录下。
    tmp = tempfile.mkdtemp(prefix="beike-deploy-", dir=os.getcwd())
    try:
        shutil.copy(args.html, os.path.join(tmp, "index.html"))
        rid = run(cli, "apps", "+html-publish", "--app-id", app_id,
                  "--path", tmp)["release_id"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("已上传，等飞书发布完…")

    deadline, url = time.time() + args.timeout, ""
    while time.time() < deadline:
        r = run(cli, "apps", "+release-get", "--release-id", rid, "--app-id", app_id)
        if r.get("status") == "finished":
            url = r.get("online_url", "")
            break
        if r.get("status") == "failed":
            sys.exit("发布失败：" + json.dumps(r.get("error_logs"), ensure_ascii=False))
        time.sleep(4)
    if not url:
        sys.exit(f"等了 {args.timeout} 秒还没发布完。用这条查：\n"
                 f"  lark-cli apps +release-get --release-id {rid} "
                 f"--app-id {app_id} --as user")

    meta_token = url.rstrip("/").rsplit("/", 1)[-1]
    make_public(cli, meta_token)
    return url


def main():
    ap = argparse.ArgumentParser(description="把背课网页发布成学生能点开的链接")
    ap.add_argument("html", help="publish.py 生成的那个 HTML 文件")
    ap.add_argument("--name", default="背单词闯关",
                    help="应用名。同名就原地更新、链接不变。默认「背单词闯关」")
    ap.add_argument("--timeout", type=int, default=180, help="等发布完成的秒数")
    args = ap.parse_args()
    url = publish(args.html, args.name, args.timeout)

    pack = read_pack(args.html)
    rs = pack.get("rosters") or {}
    print()
    print("发布好了，已设成「互联网上获得链接的人都能看」，学生不用飞书账号。")
    print()
    if len(rs) > 1:
        print(f"这一个链接发到这 {len(rs)} 个班群（学生选自己的名字，班级自动跟着走）：")
        for c, ns in rs.items():
            print(f"  · {c}　{len(ns)} 人")
    elif rs:
        print(f"发到 {next(iter(rs))} 的班群：")
    print()
    print("  " + url)
    print()
    if pack.get("title"):
        print(f"现在这个链接打开就是：{pack['title']}。")
        print("下次发新单元还用这个命令，链接不变，班群里那条可以一直置顶。")
        print()
    print("发之前自己做三件事，一件都别省：")
    print("  1. 用手机流量打开一次（不是家里 WiFi，不是电脑）")
    print("  2. 发给自己微信，从微信点进去打开一次")
    print("  3. 做完一整遍点「交作业」，回飞书表里看有没有多出来一行")
    print()
    print("页面顶上有一条飞书的壳，右上角「登录/注册」学生不用点，发群里时说一句。")


if __name__ == "__main__":
    main()
