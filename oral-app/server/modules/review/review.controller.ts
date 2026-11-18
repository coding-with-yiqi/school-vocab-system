// GET /student-api/review?班级=高一3班&姓名=林小雨 → {"packId":"review-20261118","words":[{en,zh,accept,hint}]}
// 不要登录（学生在微信里点开学生页，没有飞书身份）。只回这个学生的词和中文；限流、缓存在 logic.ts。
// 故意不放在 /api 下面：平台给 /api/* 加了 CSRF（要同域 cookie + header），学生页在飞书域名下跨域调，带不了这个 cookie。
// 这个接口只读、不改任何东西，不需要 CSRF。
import { Controller, Get, Options, Query, Req, Res } from '@nestjs/common';
import type { Request, Response } from 'express';
import { corsHeaders } from './logic';
import { ReviewService } from './review.service';

@Controller('student-api/review')
export class ReviewController {
  constructor(private readonly reviewService: ReviewService) {}

  private head(req: Request, res: Response) {
    const h = corsHeaders(String(req.headers.origin || ''), process.env.REVIEW_ALLOW_ORIGIN || '*');
    for (const [k, v] of Object.entries(h)) res.setHeader(k, v);
    res.setHeader('cache-control', 'no-store');
  }

  @Options()
  preflight(@Req() req: Request, @Res() res: Response) {
    this.head(req, res);
    res.status(204).end();
  }

  @Get()
  async get(@Query() query: Record<string, unknown>, @Req() req: Request, @Res() res: Response) {
    this.head(req, res);
    const ip = String(req.headers['x-forwarded-for'] || '').split(',')[0].trim() || req.ip || '?';
    const r = await this.reviewService.query(query, ip);
    res.status(r.status).json(r.body);
  }
}
