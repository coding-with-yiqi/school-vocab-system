# 「我的复习」现查后端（方案 A）

学生在学生页点开「我的复习」那一格时，页面才去问这个后端：「高一3班的丁一诺，现在该复习哪些词？」
后端读飞书成绩表，按 `workbuddy-skill/scripts/learning.py` 同一套规则算出来，**只回词和中文**。

- 学生页里没有任何人的复习单（以前是把全班每个人的单子烤进网页）。
- 不回分数、不回别人、不回「错在哪几课」。查一个不在名单上的名字，回空单子，不说「没这个人」。
- 查不到（后端挂了、超时、读表失败）：学生页只显示「你的复习单暂时打不开，先做本课」和一个「去做本课」按钮，不拿全班的词顶替。

## 文件

| 文件 | 干什么 |
|---|---|
| `rules.mjs` | 规则，一句一句对着 learning.py 写（compute 里每个人那段 + draft_plan + refresh）。**改 learning.py 就要改这里**，再跑 parity |
| `core.mjs` | 本地测试读飞书（lark-cli）、限流、缓存、HTTP 无关的处理函数 |
| `server.mjs` | 本地测试用的 Node 小服务，`GET /api/review` |
| `test/parity.py` | 同一份数据，learning.py 和 rules.mjs 各算一遍，逐人比 |
| `test/e2e.py` | 起着 server.mjs，用 HTTP 问，和 learning.py 比；再试不在名单的名字和限流 |

## 接口

```
GET /student-api/review?班级=高一3班&姓名=丁一诺     （线上；本地 server.mjs 是 /api/review，形状一样）
200 {"packId":"review-20261118","words":[{"en":"acknowledge","zh":"承认；致谢","accept":[...],"hint":"ack_______e"}, ...]}
400 少了姓名     429 查得太多了     502 暂时读不到
```

老师在 WorkBuddy 说的「复习 去掉 / 加上」是学期级设置，写进「复习设置」表，后端自己读，不用在请求里带。
「复习 关掉」= 学生页上没有「我的复习」这一格。

## 限流（防有人拿名单一个个试）

- 同一个 IP：一小时最多查 20 个不同的人（`REVIEW_PER_IP_STUDENTS`），十分钟最多 60 次（`REVIEW_PER_IP_10MIN`）
- 全站：一小时最多 3000 次（`REVIEW_GLOBAL_HOUR`）
- 同一个人的结果缓存 60 秒；单元 / 词表 两张表缓存 5 分钟
- ⚠️ 学校机房如果全班共用一个出口 IP，20 个人不够，要调到班级人数以上（比如 60）

## 它读哪几张表

| 表 | 列 | 谁写 |
|---|---|---|
| 成绩 | 班级 姓名 内容包 第几次 提交时间 用时偏短 还不会清单 差一点清单 明细 | 学生交作业（已有；提交时间是新加的「创建时间」列） |
| 单元 | 内容包 标题 顺序 题数 发布时间 | 真「发」的时候 `review_rows.push_all` 写（`--只生成` 不写） |
| 词表 | 内容包 词 中文 来源 **题号 变形** | 同上。题号、变形是这次新加的两列，表里没有会自动补上 |

| 复习设置 | 词 怎么办（去掉 / 加上） 中文 | `beike.py 复习 去掉 / 加上` |

第一次真发时会把课目录里所有课（含撤了的）都补进单元 / 词表，只增改不删。

## 本地跑

```bash
LARK_CLI="$HOME/.workbuddy/binaries/node/cli-connector-packages/lib/node_modules/@larksuite/cli/bin/lark-cli" \
REVIEW_BASE=<演示 base token> node server.mjs
```

对着真成绩表会拒绝启动，除非设 `REVIEW_REAL_OK=1`。本地只对着演示 base 测。

在 `~/.beike/config.json` 里加 `"review_api": "http://localhost:8787/api/review"`，再 `beike.py 课 改名 … --只生成`，生成的学生页就会点开现查。

## 线上（2026-11-17 已上妙搭）

没有新建应用，加在原来的全栈应用「背单词闯关口语」（<你的应用 id>，代码在 `../oral-app`）里：

- 接口：`GET https://<你的租户>.feishuapp.com/app/<你的应用 id>/student-api/review?班级=&姓名=`，公开、不用登录。
  - 不放在 `/api/` 下面：妙搭对 `/api/*` 一律要登录页种下的 CSRF cookie（连 GET 也要），学生页从飞书另一个域名来问，带不上。
  - 代码：`oral-app/server/modules/review/`（`logic.ts` 是规则，`review.service.ts` 查库，`review.controller.ts` 回 CORS 和 `no-store`）。
- 读表：妙搭「Base 数据同步」（`lark-cli apps +db-sync-create`）把成绩表 base 的四张表实时同步进应用自己的数据库，后端只查自己的库，**没有任何密钥**。

  | 飞书表 | 应用库里的表 | 同步了哪些列 |
  |---|---|---|
  | 成绩 | review_score | 班级 姓名 内容包 第几次 提交时间 用时偏短 还不会清单 差一点清单 明细（**分数列不同步**） |
  | 单元 | review_unit | 全部 |
  | 词表 | review_word | 全部 |
  | 复习设置 | review_setting | 全部 |

  dev 和 online 两套库各有一组同步任务（`lark-cli apps +db-sync-list --app-id <你的应用 id>`）。dev 那组会把真成绩也同步进开发库，不想要就 `+db-sync-disable`。
- 没用多维表格插件：插件只能在妙搭平台上调；插件自带的 `/api/capability/<实例>` 不登录也能调，会把整张成绩表露出去。插件已经卸了，朗读插件 ai-speech-synthesis 留着。
- 同步任务删了重建时，新任务第一次只拉进来一行（实测）。重建后在老师电脑上再写一遍单元 / 词表（`review_rows.push_all`，真「发」一次也会写）就补齐了。
- 改了后端代码：在 `oral-app` 里 commit、push，再 `lark-cli apps +release-create --app-id <你的应用 id> --as user`。加了新列要先 `+db-env-migrate`。

### 学生页也在这里（2026-11-18）

- `GET /student-api/page`（https://<你的租户>.feishuapp.com/app/<你的应用 id>/student-api/page）：读本应用库 `student_page` 表最新一行，整页回给浏览器（text/html，no-store，同一时间点开的人 10 秒内共用一次查询）。代码 `oral-app/server/modules/review/page.controller.ts`。
- 写：`beike.py` 的 `page_to_db`，用 `lark-cli apps +db-execute --file` 插一行（HTML 用 base64 包着），只留最近 30 版。设了 BEIKE_HOME 时写 dev 库。
- 表：`student_page(id, html, note, created_at)`，开了 RLS，anon / authenticated 只能读。
- 学生页和 review 接口同域，不再跨域。

### 跨域

后端回 `Access-Control-Allow-Origin: *`，请求是简单 GET，浏览器不发预检。2026-11-17 用真数据生成的学生页（本机 http 打开）点「我的复习」，请求线上接口回 200，页面显示正常。**飞书里、手机流量下还没点过。**
