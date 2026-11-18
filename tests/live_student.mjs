// 真打开线上学生页（不拦网络、不改时钟），选第一个学生做完一课。
// 只在页面里读出判分、结果码和表单预填链接，不点「提交」，不往飞书写任何东西。
//   node live_student.mjs <playwright 目录> <线上学生页地址> <输出.json>
import { createRequire } from "node:module";
import { writeFileSync } from "node:fs";

const [pwDir, url, outFile] = process.argv.slice(2);
const { chromium } = createRequire(import.meta.url)(pwDir);

// 每题怎么答：按题在这一课里的序号轮着来 —— 对 / 差一个字母 / 乱写 / 对（改错题双数号错因选错）
function answerFor(it, k) {
  const right = (it.accept && it.accept[0]) || it.answer || it.en || "";
  if (it.type === "compose") return k % 2 ? "short " + (it.must || []).join(" ")
    : "I think " + (it.must || []).join(" and ") + " are really important in our daily life.";
  if (it.type === "cloze") return k % 3 === 2 ? (it.options || []).find(o => o !== it.answer) || right : right;
  const m = k % 4;
  if (m === 1 && right.length > 3) return right.slice(0, -2) + right.slice(-1);
  if (m === 2) return "zzz qqq";
  return right;
}

const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const log = [];
  page.on("pageerror", e => log.push("页面报错：" + e.message));
  page.on("request", r => { if (r.method() !== "GET" && r.method() !== "OPTIONS") log.push("有非 GET 请求：" + r.method() + " " + new URL(r.url()).pathname) });
  await page.goto(url, { waitUntil: "networkidle" });
  const out = { tag: "书_线上", log };
  const VIEWS = '["v-start","v-intro","v-scene","v-level","v-done"].filter(v=>document.getElementById(v)).find(v=>!$(v).classList.contains("hide"))';
  const book = await page.evaluate(() => typeof BOOK !== "undefined");
  out.template = book ? "书（assets/student.html）" : "不是书：线上页面不是 assets/student.html 生成的";
  out.items = await page.evaluate(book => {
    const r = {}, packs = book ? BOOK.packs : [PACK];
    for (const p of packs) for (const [id, it] of Object.entries(p.items || {})) r[p.packId + "/" + id] = it;
    return r;
  }, book);
  // judge() 对每一课每一题：答对 / 空 / 乱写 / 去掉第一个字母；后面跟 shortOf 的标签
  out.judge = await page.evaluate(book => {
    const r = {}, packs = book ? BOOK.packs : [PACK];
    for (const p of packs) for (const [id, it] of Object.entries(p.items || {})) {
      const right = (it.accept && it.accept[0]) || it.answer || it.en || "";
      let label;
      if (book) { const old = IT; IT = p.items || {}; label = shortOf(id); IT = old } else label = shortOf(id);
      r[p.packId + "/" + id] = [right, "", "zzz", right.slice(1)].map(a => judge(it, a).r).join(",") + " " + label;
    }
    return r;
  }, book);
  await page.selectOption("#pick", "0|1");
  await page.click("#btn-start");
  // 「我的复习」那一格会去线上现查，等它查完再往下
  if (book && await page.evaluate(() => !!LIVE))
    await page.waitForFunction(() => !TABS.find(t => t.live).loading, null, { timeout: 20000 });
  out.afterStart = await page.evaluate(V => ({ view: eval(V),
    intro: $("i-title") ? $("i-title").textContent : "", resume: $("i-resume") ? $("i-resume").textContent : "",
    open: $("btn-open") ? $("btn-open").textContent : "", tab: typeof P !== "undefined" && P ? P.packId : PACK.packId }), VIEWS);
  out.liveSub = book ? await page.textContent("#i-sub") : "";
  if (book && (await page.textContent("#btn-open")) === "去做本课") await page.click("#btn-open");
  out.pack = await page.evaluate(() => typeof P !== "undefined" && P ? P.packId : PACK.packId);
  let k = 0;
  for (let guard = 0; guard < 40; guard++) {
    const view = await page.evaluate(V => eval(V), VIEWS);
    if (view === "v-done") break;
    if (view === "v-intro") { await page.click("#btn-open"); continue }
    if (view === "v-scene") { await page.click("#btn-go"); continue }
    const ids = await page.evaluate(() => qlist());
    for (const id of ids) {
      const it = await page.evaluate(id => IT[id], id);
      const a = answerFor(it, k++);
      if (it.type === "cloze") await page.click(`.opt[data-q="${id}"][data-v="${a}"]`);
      else await page.fill(`#in-${id}`, a);
      if (it.type === "fix") {
        const rs = it.reasons || [];
        const pick = k % 2 ? it.reason : (rs.find(x => x !== it.reason) || it.reason);
        if (pick) await page.click(`.opt[data-q="r-${id}"][data-v="${pick}"]`);
      }
    }
    await page.click("#btn-check");
    out["关卡" + guard] = await page.evaluate(() => $("lv-msg").textContent);
    await page.click("#btn-next");
  }
  await page.evaluate(() => renderDone());
  await page.click('#self-opts .opt >> nth=1');
  out.done = await page.evaluate(() => ({ title: $("d-title").textContent, sub: $("d-sub").textContent,
    wrong: [...document.querySelectorAll("#d-wrong li")].map(x => x.textContent),
    code: $("d-code").textContent, payload: payload(), prefill: submitUrl(), how: $("d-how").textContent }));
  writeFileSync(outFile, JSON.stringify(out, null, 1));
  console.log("  做的课：" + out.pack + "　关卡 " + Object.keys(out).filter(k => k.startsWith("关卡")).length + " 个　「我的复习」：" + out.liveSub);
  console.log("  页面报错 / 非 GET 请求：" + (log.join("；") || "无"));
} finally {
  await browser.close();
}
