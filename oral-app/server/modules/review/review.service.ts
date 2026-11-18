// 「我的复习」现查：飞书多维表格的四张表由妙搭「Base 数据同步」实时同步进本应用的数据库（不用密钥），
// 这里只读本应用的库，交给 logic.ts 算。同步任务是用 lark-cli apps +db-sync-create 建的，只同步算复习要用的列：
//   review_score   成绩：班级 姓名 内容包 第几次 提交时间 用时偏短 还不会清单 差一点清单 明细（分数那几列没同步过来）
//   review_unit    单元：内容包 标题 顺序 题数 发布时间
//   review_word    词表：内容包 词 中文 来源 题号 变形
//   review_setting 复习设置：词 怎么办 中文
// 库里的列名是同步时自动起的英文名，这里用 AS "中文名" 换回 logic.ts 认的飞书列名。
import { Inject, Injectable, Logger } from '@nestjs/common';
import { DRIZZLE_DATABASE, type PostgresJsDatabase } from '@lark-apaas/fullstack-nestjs-core';
import { sql, type SQL } from 'drizzle-orm';
import { makeHandler } from './logic';
import type { Reader, Result, Row } from './logic';

const SCORE_COLS = sql.raw(`app_class AS "班级", app_name AS "姓名", content_package AS "内容包",
  which_time::float8 AS "第几次", (extract(epoch from submit_time) * 1000)::float8 AS "提交时间",
  time_too_short AS "用时偏短", not_yet_list AS "还不会清单", almost_list AS "差一点清单", details AS "明细"`);

const TABLES: Record<string, SQL> = {
  单元: sql.raw(`SELECT content_package AS "内容包", title AS "标题", app_sequence::float8 AS "顺序",
    question_count::float8 AS "题数", publish_time AS "发布时间" FROM review_unit`),
  词表: sql.raw(`SELECT content_package AS "内容包", app_word AS "词", chinese AS "中文", source AS "来源",
    app_question_num AS "题号", app_deformation AS "变形" FROM review_word`),
  复习设置: sql.raw(`SELECT word AS "词", what_to_do AS "怎么办", chinese AS "中文" FROM review_setting`),
};

@Injectable()
export class ReviewService {
  private readonly logger = new Logger('ReviewService');
  private readonly handle: (q: Record<string, unknown>, ip: string) => Promise<Result>;

  constructor(@Inject(DRIZZLE_DATABASE) private readonly db: PostgresJsDatabase) {
    const reader: Reader = {
      rows: (table) => (TABLES[table] ? this.run(TABLES[table]) : Promise.resolve([])),
      student: (cls, name) =>
        this.run(
          cls
            ? sql`SELECT ${SCORE_COLS} FROM review_score WHERE app_name = ${name} AND app_class = ${cls}`
            : sql`SELECT ${SCORE_COLS} FROM review_score WHERE app_name = ${name}`,
        ),
    };
    this.handle = makeHandler({ reader, log: (m) => this.logger.error(m) });
  }

  private async run(q: SQL): Promise<Row[]> {
    const r = (await this.db.execute(q)) as unknown;
    return (Array.isArray(r) ? r : ((r as { rows?: Row[] }).rows ?? [])) as Row[];
  }

  query(q: Record<string, unknown>, ip: string): Promise<Result> {
    return this.handle(q, ip);
  }
}
