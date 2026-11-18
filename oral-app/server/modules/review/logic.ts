// 「我的复习」现查：一个学生还没拿下哪些词。这是唯一的一份规则（妙搭后端用它，review-api 的本地测试也直接 import 它）。
//
// 规则和 workbuddy-skill/scripts/learning.py 一字一句对着写（compute 里「每个人」那一段 + draft_plan + apply_settings + refresh），
// 改那边就要改这边，再跑 review-api/test/parity.py，逐人对上才算改完。
//
// 输入全是飞书里读出来的行：
//   records  这个学生的成绩行（班级 姓名 内容包 第几次 提交时间 用时偏短 还不会清单 差一点清单 明细）
//   units    单元表（内容包 顺序 发布时间）——排课的先后
//   words    词表（内容包 词 中文 来源 题号 变形）——题号对回词
//   settings 复习设置表（词 怎么办=去掉|加上 中文）——老师说的全班「去掉 / 加上」，学期级
// 输出只有词和中文（外加学生页出题要的 accept / hint，都是从词本身算出来的），不带分数、不带别人。
//
// 只用「能直接擦掉的」TypeScript 写法（type、参数类型），没有 import：Node 22+ 能直接跑这个文件。

export type Row = Record<string, unknown>;
type State = { 状态: string; 错在哪几课: string[]; 连续对几次: number };
type Pack = { idWord: Map<string, string>; surface: Map<string, string>; zh: Map<string, string>; vocab: string[] };
type Order = Map<string, [string, number]>;
export type Word = { en: string; zh: string; accept: string[]; hint: string };
export type Reader = { rows(table: string): Promise<Row[]>; student(cls: string, name: string): Promise<Row[]> };
export type Result = { status: number; body: Record<string, unknown> };

const WORD_RE = /^[A-Za-z][A-Za-z '\-]*$/;
const RIGHT = "对", SHAKY = "差一点", WRONG = "还不会";
const RES: Record<string, string> = { pass: RIGHT, ok: RIGHT, near: SHAKY, fail: WRONG, no: WRONG, "-": WRONG };
const RANK: Record<string, number> = { [RIGHT]: 0, [SHAKY]: 1, [WRONG]: 2 };
export const PER_STUDENT = 20;
const ONLY_CLOZE = "只在填空";

// ── learning._s / _num / _split / key_of / rid / _when
export function s(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (Array.isArray(v)) return v.map(x => (x && typeof x === "object") ? String((x as Row).text ?? (x as Row).name ?? JSON.stringify(x)) : String(x)).join("、");
  if (typeof v === "object") {
    const o = v as Row;
    if ("text" in o) return String(o.text).trim();
    if (Array.isArray(o.value)) return s(o.value);
    return JSON.stringify(v);
  }
  return String(v).trim();
}
export function num(v: unknown, d = 0): number {
  const t = s(v);
  if (t === "" || !Number.isFinite(Number(t))) return d;
  return Math.trunc(Number(t));
}
// 提交时间（飞书「创建时间」列）：毫秒数或「2026-11-17 15:20」这样的文字都能比；没有就排最后
export function when(v: unknown): number {
  const t = s(v);
  if (!t) return Infinity;
  if (Number.isFinite(Number(t))) return Number(t);
  const d = t.replace(/\D/g, "");
  return d ? Number(d) : Infinity;
}
const split = (v: unknown) => s(v).split(/[、,，]/).map(x => x.trim()).filter(Boolean);
export const keyOf = (r: Row) => `${s(r["班级"])}·${s(r["姓名"])}`;
export const rid = (en: string) => "R-" + en.replace(/[^A-Za-z0-9-]+/g, "_");
const cmpStr = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);
const cmpNum = (a: number, b: number) => (a < b ? -1 : a > b ? 1 : 0);

// ── build_pack.accept_of / hint_of（学生页出题用，和发课时一样）
export function hintOf(en: string): string {
  const body = en.trim().split(/\s+/)[0];
  if (body.length <= 3) return body[0] + "_".repeat(body.length - 1);
  const keep = body.length >= 8 ? 3 : 2;
  return body.slice(0, keep) + "_".repeat(body.length - keep - 1) + body[body.length - 1];
}
export function acceptOf(en: string): string[] {
  const acc = new Set([en.toLowerCase()]);
  const head = en.trim().split(/\s+/)[0].toLowerCase();
  acc.add(head);
  if (/^[a-z]+$/.test(head)) {
    acc.add(head + "s");
    acc.add(head.endsWith("e") ? head + "d" : head + "ed");
  }
  return [...acc].sort(cmpStr);
}

// ── 词表 → 每一课：题号→词、变形→词、这一课考的词（learning.PackInfo）
export function packInfo(words: Row[]): Map<string, Pack> {
  const info = new Map<string, Pack>();
  for (const r of words) {
    const pid = s(r["内容包"]), w = s(r["词"]);
    if (!pid || !w) continue;
    let pi = info.get(pid);
    if (!pi) info.set(pid, pi = { idWord: new Map(), surface: new Map(), zh: new Map(), vocab: [] });
    if (s(r["来源"]) !== ONLY_CLOZE) pi.vocab.push(w);
    if (s(r["中文"])) pi.zh.set(w, s(r["中文"]));
    for (const id of s(r["题号"]).split(/[\s,，、]+/).filter(Boolean)) pi.idWord.set(id, w);
    for (const f of s(r["变形"]).split(/[\s,，、]+/).filter(Boolean)) pi.surface.set(f.toLowerCase(), w);
  }
  return info;
}

// 单元表里的发布时间可能是文字，也可能是日期列（毫秒数）
function dayOf(v: unknown): string {
  if (typeof v === "number" && v > 1e11) return new Date(v + 8 * 3600e3).toISOString().slice(0, 10);   // 北京时间
  return s(v).slice(0, 10);
}
function dayFromId(pid: string): string {
  const m = pid.match(/(20\d{2})(\d{2})(\d{2})/);
  return m ? `${m[1]}-${m[2]}-${m[3]}` : "9999";
}
export function orderOf(units: Row[]): Order {
  const out: Order = new Map();
  for (const u of units) {
    const pid = s(u["内容包"]);
    if (pid) out.set(pid, [dayOf(u["发布时间"]) || "9999", num(u["顺序"]) || 1e6]);
  }
  return out;
}

// ── learning._outcomes
function outcomes(r: Row, pi: Pack | undefined, vocab: string[], rmap: Map<string, string>): Map<string, string> {
  const out = new Map<string, string>();
  const put = (w: string | null | undefined, o: string) => { if (w && (!out.has(w) || RANK[o] > RANK[out.get(w) as string])) out.set(w, o) };
  const detail = s(r["明细"]);
  const ids = pi ? pi.idWord : new Map<string, string>();
  if (detail && (ids.size || detail.includes("R-"))) {
    for (const part of detail.split(",")) {
      const i = part.indexOf(":");
      if (i < 0) continue;
      const iid = part.slice(0, i).trim(), res = part.slice(i + 1);
      const w = ids.get(iid) || (iid.startsWith("R-") ? (rmap.get(iid) || iid.slice(2).replace(/_/g, " ")) : null);
      const o = RES[res.split(">")[0].trim()];
      if (w && o) put(w, o);
    }
    if (out.size) return out;
  }
  const surface = pi ? pi.surface : new Map<string, string>();
  const lower = new Map(vocab.map(w => [w.toLowerCase(), w]));
  const norm = (lab: string) => WORD_RE.test(lab) ? (surface.get(lab.toLowerCase()) || lower.get(lab.toLowerCase()) || lab) : null;
  for (const lab of split(r["还不会清单"])) put(norm(lab), WRONG);
  for (const lab of split(r["差一点清单"])) put(norm(lab), SHAKY);
  for (const w of vocab) put(w, RIGHT);
  return out;
}

// ── learning.compute 里「每个人」那一段，只算一个人：{词: {状态, 错在哪几课, 连续对几次}}
export function studentState(records: Row[], units: Row[], words: Row[], key?: string) {
  const info = packInfo(words), order = orderOf(units);
  const rmap = new Map<string, string>();
  for (const pi of info.values()) {
    for (const w of pi.vocab) rmap.set(rid(w), w);
    for (const w of pi.zh.keys()) rmap.set(rid(w), w);
    for (const w of pi.idWord.values()) rmap.set(rid(w), w);
  }
  const okey = (pid: string): [string, number] => order.get(pid) || [dayFromId(pid), 1e6];
  const by = new Map<string, Row[]>();
  for (const r of records) {
    if (!s(r["姓名"]) || !s(r["内容包"]) || (key && keyOf(r) !== key)) continue;
    const pid = s(r["内容包"]);
    if (!by.has(pid)) by.set(pid, []);
    (by.get(pid) as Row[]).push(r);
  }
  const events: [[string, number], string, Map<string, string>][] = [];
  for (const [pid, rs0] of by) {
    // 同一课：先按第几次，再按提交时间（换手机时两份都是「第 1 次」，早交的那份算）
    const rs = rs0.slice().sort((a, b) => cmpNum(num(a["第几次"], 1), num(b["第几次"], 1)) || cmpNum(when(a["提交时间"]), when(b["提交时间"])));
    const good = rs.find(r => s(r["用时偏短"]) !== "是");
    if (!good) continue;
    const pi = info.get(pid);
    events.push([okey(pid), pid, outcomes(good, pi, pi ? pi.vocab : [], rmap)]);
  }
  events.sort((a, b) => cmpStr(a[0][0], b[0][0]) || (a[0][1] - b[0][1]) || cmpStr(a[1], b[1]));
  const mine: Record<string, State> = {};
  for (const [, pid, outs] of events) {
    for (const [w, o] of outs) {
      let st = mine[w];
      if (o !== RIGHT) {
        st = mine[w] ||= { 状态: o, 错在哪几课: [], 连续对几次: 0 };
        st.状态 = o; st.连续对几次 = 0;
        if (!st.错在哪几课.includes(pid)) st.错在哪几课.push(pid);
      } else if (st && st.状态 !== "拿下") {
        st.连续对几次 += 1;
        if (st.连续对几次 >= 2) st.状态 = "拿下";
      }
    }
  }
  return { mine, handedIn: events.length > 0, info, order };
}

// 中文：后面的课说了算（同一个词两课写的中文不一样时）
function zhTable(info: Map<string, Pack>, order: Order): Map<string, string> {
  const zh = new Map<string, string>();
  const pids = [...info.keys()].sort((a, b) => {
    const x = order.get(a) || [dayFromId(a), 1e6], y = order.get(b) || [dayFromId(b), 1e6];
    return cmpStr(x[0], y[0]) || (x[1] - y[1]) || cmpStr(a, b);
  });
  for (const pid of pids) for (const [w, z] of (info.get(pid) as Pack).zh) if (z) zh.set(w, z);
  return zh;
}

// 复习设置表 → 去掉 / 加上（learning.load_settings）。同一个词只有一行，怎么办是空的就是不管了。
export function readSettings(rows: Row[]) {
  const drop: string[] = [], add: string[] = [], addZh = new Map<string, string>();
  for (const r of rows) {
    const w = s(r["词"]), how = s(r["怎么办"]);
    if (!w || !WORD_RE.test(w)) continue;
    if (how === "去掉") drop.push(w);
    else if (how === "加上") { add.push(w); if (s(r["中文"])) addZh.set(w, s(r["中文"])) }
  }
  return { drop, add, addZh };
}

// ── review_lists → draft_plan（有中文的前 20 个）→ refresh（去掉 / 加上）→ 学生页只放有中文的
export function reviewList({ records, units, words, key, drop = [], add = [], addZh = new Map() }:
  { records: Row[]; units: Row[]; words: Row[]; key?: string; drop?: string[]; add?: string[]; addZh?: Map<string, string> }): Word[] {
  const { mine, handedIn, info, order } = studentState(records, units, words, key);
  const zh = zhTable(info, order);
  for (const [w, z] of addZh) if (!zh.get(w) && add.includes(w)) zh.set(w, z);    // 加上的词，课里没有中文时用设置里的
  const left = Object.keys(mine).filter(w => mine[w].状态 !== "拿下")
    .sort((a, b) => (mine[b].错在哪几课.length - mine[a].错在哪几课.length) || cmpStr(a, b));
  const dropL = new Set(drop.map(w => w.toLowerCase()));
  let list = left.filter(w => zh.get(w)).slice(0, PER_STUDENT).filter(w => !dropL.has(w.toLowerCase()));
  if (handedIn) {                       // 「加上」只给交过作业的人（learning 里的「学生们」）
    const got = new Set(Object.keys(mine).filter(w => mine[w].状态 === "拿下").map(w => w.toLowerCase()));
    for (const w of add) {
      if (!got.has(w.toLowerCase()) && !list.some(x => x.toLowerCase() === w.toLowerCase())) list.push(w);
    }
  }
  list = list.filter(w => zh.get(w));
  return list.map(en => ({ en, zh: zh.get(en) as string, accept: acceptOf(en), hint: hintOf(en) }));
}

// 「我的复习」这一轮的 packId：北京时间的今天（一天一份，和老的 review-<日期> 一样）
export function reviewPackId(now = Date.now()): string {
  return "review-" + new Date(now + 8 * 3600e3).toISOString().slice(0, 10).replace(/-/g, "");
}

// ── 限流：一个 IP 一小时最多查几个不同的人、十分钟最多几次；全站一小时最多几次。可以用环境变量调。
const env = (k: string) => Number((globalThis as unknown as { process?: { env: Record<string, string | undefined> } }).process?.env[k]) || 0;
export function makeLimiter({
  perIpStudentsPerHour = env("REVIEW_PER_IP_STUDENTS") || 20,
  perIpPer10Min = env("REVIEW_PER_IP_10MIN") || 60,
  globalPerHour = env("REVIEW_GLOBAL_HOUR") || 3000,
} = {}) {
  const ips = new Map<string, { hits: number[]; who: Map<string, number> }>();
  let global: number[] = [];
  return function allow(ip: string, who: string, now = Date.now()): boolean {
    const hour = now - 3600e3, ten = now - 600e3;
    global = global.filter(t => t > hour);
    let e = ips.get(ip);
    if (!e) ips.set(ip, e = { hits: [], who: new Map() });
    e.hits = e.hits.filter(t => t > ten);
    for (const [k, t] of e.who) if (t <= hour) e.who.delete(k);
    if (global.length >= globalPerHour) return false;
    if (e.hits.length >= perIpPer10Min) return false;
    if (!e.who.has(who) && e.who.size >= perIpStudentsPerHour) return false;
    e.hits.push(now); e.who.set(who, now); global.push(now);
    if (ips.size > 50000) ips.clear();             // 防止被刷爆内存
    return true;
  };
}

// ── 处理一次查询（和 HTTP 无关）：单元 / 词表 / 复习设置 全班都一样，缓存几分钟；一个人的结果缓存一分钟
const NAME_MAX = 40;
export function makeHandler({ reader, limiter = makeLimiter(), tableTtl = 300e3, personTtl = 60e3, now = () => Date.now(),
  log = (m: string) => console.error(m) }:  // eslint-disable-line no-console -- 只给本地 review-api/server.mjs 兜底；Nest 里传 Logger
  { reader: Reader; limiter?: (ip: string, who: string, now?: number) => boolean; tableTtl?: number; personTtl?: number;
    now?: () => number; log?: (m: string) => void }) {
  let shared: { units: Row[]; words: Row[]; settings: ReturnType<typeof readSettings> } | null = null, sharedAt = 0;
  let sharedP: Promise<NonNullable<typeof shared>> | null = null;
  const people = new Map<string, { at: number; body: Record<string, unknown> }>();
  function tables() {
    if (shared && now() - sharedAt < tableTtl) return Promise.resolve(shared);
    return sharedP ||= Promise.all([reader.rows("单元"), reader.rows("词表"), reader.rows("复习设置")])
      .then(([units, words, set]) => { shared = { units, words, settings: readSettings(set) }; sharedAt = now(); return shared })
      .finally(() => { sharedP = null });
  }

  return async function handle(query: Record<string, unknown>, ip: string): Promise<Result> {
    const cls = String(query["班级"] || "").trim().slice(0, NAME_MAX);
    const name = String(query["姓名"] || "").trim().slice(0, NAME_MAX);
    if (!name) return { status: 400, body: { error: "少了姓名" } };
    const key = `${cls}·${name}`;
    if (!limiter(ip || "?", key, now())) return { status: 429, body: { error: "查得太多了，过一会儿再试" } };
    const hit = people.get(key);
    if (hit && now() - hit.at < personTtl) return { status: 200, body: hit.body };
    try {
      const [t, recs] = await Promise.all([tables(), reader.student(cls, name)]);
      const mine = recs.filter(r => keyOf(r) === key);       // 搜索是「包含」时也只留这个人自己的
      const words = reviewList({ records: mine, units: t.units, words: t.words, key,
        drop: t.settings.drop, add: t.settings.add, addZh: t.settings.addZh });
      const body = { packId: reviewPackId(now()), words };
      people.set(key, { at: now(), body });
      if (people.size > 5000) people.clear();
      return { status: 200, body };
    } catch (e) {
      log("[review] 读表失败：" + (e instanceof Error ? e.message : String(e)));
      return { status: 502, body: { error: "暂时读不到" } };
    }
  };
}

export function corsHeaders(origin: string, allowList = "*"): Record<string, string> {
  const allow = allowList.split(",").map(x => x.trim());
  const o = allow.includes("*") ? "*" : (allow.includes(origin) ? origin : allow[0]);
  return { "access-control-allow-origin": o, "access-control-allow-methods": "GET, OPTIONS",
    "access-control-allow-headers": "content-type", "access-control-max-age": "86400", vary: "Origin" };
}
