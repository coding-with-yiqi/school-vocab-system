// 本地测试用的读飞书办法（lark-cli）。规则、限流、处理函数都在 oral-app/server/modules/review/logic.ts（经 rules.mjs 转过来），
// 线上妙搭后端不走这里：四张表用妙搭「Base 数据同步」同步进应用自己的库，review.service.ts 直接查库。
// 线上地址是 /student-api/review（不在 /api 下，躲开妙搭的 CSRF）；本地 server.mjs 还用 /api/review，形状一样。
//
//   GET /api/review?班级=高一3班&姓名=林小雨
//   → 200 {"packId":"review-20261118","words":[{"en":"physician","zh":"内科医生","accept":[...],"hint":"phy____n"}]}
//
// 读者接口：{ rows(表名) → 行[]（表不存在回 []），student(班级, 姓名) → 这个人的成绩行 }
import { execFile } from "node:child_process";
export { makeHandler, makeLimiter, corsHeaders } from "./rules.mjs";

// 本地测试：lark-cli，用本机已登录的身份（--as user）。只用来对着演示 base 测。
export function larkCliReader({ base, cli = "lark-cli" }) {
  const run = args => new Promise((ok, no) => execFile(cli, [...args, "--as", "user", "--format", "json"],
    { maxBuffer: 64 << 20 }, (err, out, errOut) => {
      let d; try { d = JSON.parse(out || errOut) } catch { return no(new Error("lark-cli 没回 JSON")) }
      if (!d.ok) return no(new Error((d.error || {}).message || "lark-cli 失败"));
      ok(d.data || {});
    }));
  const matrix = d => (d.data || []).map(row => Object.fromEntries((d.fields || []).map((f, i) => [f, row[i]])));
  let names = null;
  const has = async t => (names ||= (await run(["base", "+table-list", "--base-token", base])).tables.map(x => x.name)).includes(t);
  return {
    async rows(table) {
      if (!(await has(table))) return [];
      let out = [], offset = 0;
      for (;;) {
        const d = await run(["base", "+record-list", "--base-token", base, "--table-id", table,
          "--offset", String(offset), "--limit", "200"]);
        out = out.concat(matrix(d));
        if (!d.has_more) return out;
        offset += 200;
      }
    },
    async student(cls, name) {
      const conds = [["姓名", "==", name]];
      if (cls) conds.push(["班级", "==", cls]);
      const d = await run(["base", "+record-search", "--base-token", base, "--table-id", "成绩",
        "--keyword", name, "--search-field", "姓名", "--limit", "200",
        "--filter-json", JSON.stringify({ logic: "and", conditions: conds })]);
      return matrix(d);
    },
  };
}
