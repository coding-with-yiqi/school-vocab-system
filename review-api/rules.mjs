// 规则只有一份：oral-app/server/modules/review/logic.ts（妙搭后端就是它）。这里转一下，给本地测试和 server.mjs 用。
// Node 22.18+ / 23.6+ 能直接 import .ts（只用了能擦掉的类型写法）。
export * from "../oral-app/server/modules/review/logic.ts";
