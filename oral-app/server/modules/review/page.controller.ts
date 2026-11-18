// GET /student-api/page → 最新一版学生页（整页 HTML）。学生链接就是这个地址，永远不变。
// 为什么不用妙搭 html 应用：html 应用跑在 iframe 里，平台注入的 CSP 拦掉了「我的复习」的请求（connect-src），
// 也拦掉了「交作业」跳飞书表单（iframe 里跳不出去）。全栈应用在顶层打开，没有这些限制。
// 页面存在本应用库的 student_page 表里：老师电脑「发」的时候插一行（lark-cli apps +db-execute），这里读最新一行。
// 所以每次发课不用重新发布这个应用。页面里没有任何密钥；不要登录。
import { Controller, Get, Inject, Logger, Res } from '@nestjs/common';
import { DRIZZLE_DATABASE, type PostgresJsDatabase } from '@lark-apaas/fullstack-nestjs-core';
import { sql } from 'drizzle-orm';
import type { Response } from 'express';

const FALLBACK = `<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>背单词闯关</title><body style="font-family:system-ui;padding:32px 20px;color:#333">
<p>页面暂时打不开，过一会儿再点一次链接。</p></body></html>`;

@Controller('student-api/page')
export class PageController {
  private readonly logger = new Logger('PageController');
  private cache: { html: string; at: number } | null = null;

  constructor(@Inject(DRIZZLE_DATABASE) private readonly db: PostgresJsDatabase) {}

  private async latest(): Promise<string | null> {
    if (this.cache && Date.now() - this.cache.at < 10_000) return this.cache.html;   // 同时点开的人共用一次查询
    const r = (await this.db.execute(sql`SELECT html FROM student_page ORDER BY id DESC LIMIT 1`)) as unknown;
    const rows = (Array.isArray(r) ? r : ((r as { rows?: unknown[] }).rows ?? [])) as { html?: string }[];
    const html = rows[0]?.html ?? null;
    if (html) this.cache = { html, at: Date.now() };
    return html;
  }

  @Get()
  async get(@Res() res: Response) {
    res.setHeader('content-type', 'text/html; charset=utf-8');
    res.setHeader('cache-control', 'no-store');
    res.setHeader('x-content-type-options', 'nosniff');
    try {
      const html = await this.latest();
      res.status(html ? 200 : 503).send(html ?? FALLBACK);
    } catch (e) {
      this.logger.error(`读学生页失败：${(e as Error).message}`);
      res.status(503).send(this.cache?.html ?? FALLBACK);
    }
  }
}
