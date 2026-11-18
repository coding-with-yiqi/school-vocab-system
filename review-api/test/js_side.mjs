// parity.py 调这个：读 {records, units, words, drop, add}，每个学生用 rules.mjs 算一遍，输出 JSON
import { readFileSync } from "node:fs";
import { studentState, reviewList, keyOf } from "../rules.mjs";
const d = JSON.parse(readFileSync(process.argv[2], "utf8"));
const keys = [...new Set(d.records.filter(r => r["姓名"] && r["内容包"]).map(keyOf))];
const out = {};
for (const key of keys) {
  // 后端只拿得到这个人的行：先按人筛，再算（和线上一样）
  const mine = d.records.filter(r => keyOf(r) === key);
  out[key] = {
    state: studentState(mine, d.units, d.words, key).mine,
    list: reviewList({ records: mine, units: d.units, words: d.words, key, drop: d.drop, add: d.add }),
  };
}
process.stdout.write(JSON.stringify(out));
