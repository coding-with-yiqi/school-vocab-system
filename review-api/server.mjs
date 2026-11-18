// 本地测试用的后端：node server.mjs，默认读 ~/.beike/config.json 里的 demo_base（演示 base），不碰真成绩表。
//   PORT=8787  REVIEW_BASE=<base token>（不给就用 demo_base）
//   LARK_CLI=<lark-cli 的完整路径>（这台电脑上 lark-cli 不在 PATH 里，在 ~/.workbuddy/binaries/node/cli-connector-packages/…/bin/lark-cli）
import http from "node:http";
import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { makeHandler, larkCliReader, corsHeaders } from "./core.mjs";

const cfg = (() => { try { return JSON.parse(readFileSync((process.env.BEIKE_HOME || homedir() + "/.beike") + "/config.json", "utf8")) } catch { return {} } })();
const base = process.env.REVIEW_BASE || cfg.demo_base;
if (!base) { console.error("没有 base：给 REVIEW_BASE，或者在 ~/.beike/config.json 里放 demo_base"); process.exit(1) }
if (cfg.base && base === cfg.base && !process.env.REVIEW_REAL_OK) {
  console.error("这是真成绩表。本地测试只对着演示 base；真要读，设 REVIEW_REAL_OK=1。"); process.exit(1);
}
const reader = larkCliReader({ base, cli: process.env.LARK_CLI || "lark-cli" });
const handle = makeHandler({ reader });

http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://x");
  const cors = corsHeaders(req.headers.origin || "", process.env.REVIEW_ALLOW_ORIGIN || "*");
  const send = (status, body) => {
    res.writeHead(status, { ...cors, "content-type": "application/json; charset=utf-8", "cache-control": "no-store" });
    res.end(body === undefined ? "" : JSON.stringify(body));
  };
  if (req.method === "OPTIONS") return send(204);
  if (req.method !== "GET" || url.pathname !== "/api/review") return send(404, { error: "没有这个地址" });
  const ip = (process.env.TRUST_PROXY && String(req.headers["x-forwarded-for"] || "").split(",")[0].trim())
    || req.socket.remoteAddress;
  const r = await handle(Object.fromEntries(url.searchParams), ip);
  console.log(new Date().toISOString(), r.status, ip, (r.body.words || []).length);   // 不记名字
  send(r.status, r.body);
}).listen(+process.env.PORT || 8787, () => console.log(`复习现查：http://localhost:${+process.env.PORT || 8787}/api/review （base …${base.slice(-4)}）`));
