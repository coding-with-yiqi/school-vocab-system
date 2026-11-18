import { Module } from '@nestjs/common';
import { ReviewController } from './review.controller';
import { ReviewService } from './review.service';
import { PageController } from './page.controller';

// 学生用的两个口子：GET /student-api/page（学生页本身）和 GET /student-api/review（「我的复习」按人回词）。
// 表都在本应用的库里，前端拿不到，只有这两个接口读。
// 没有装多维表格插件（插件自带的 /api/capability/<实例> 不登录也能调，会把整张成绩表露出去）。
// 朗读插件（ai-speech-synthesis）照旧留着，以后听写要用。
@Module({
  controllers: [ReviewController, PageController],
  providers: [ReviewService],
})
export class ReviewModule {}
