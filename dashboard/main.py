"""数据看板后端：FastAPI 读 articles 表 + 托管前端构建产物。

两个数据接口（前端页面消费）：
  GET /api/stats            统计汇总（总数/今日/域名分布/按日趋势）
  GET /api/articles?page=&size=   文章分页列表

设计说明：
  - 看板是低频访问的展示层，直接"每请求新建连接"（连接池对它属于过度设计）
  - SQL 全部参数绑定；page/size 由 FastAPI 强制成 int（type hints 即校验）
  - 生产模式：本服务同时托管 frontend/dist 静态文件（前后端同源，无跨域）
"""

import os

import psycopg2
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

DSN = os.environ.get(
    'CRAWLER_DSN',
    'postgresql://postgres:postgres@localhost:5433/crawler',
)

app = FastAPI(title='News Crawler Dashboard')

# 开发模式跨域放行：本地 npm run dev（5173）调试时需要；
# 生产模式前后端同源（本服务托管 dist），此配置不影响安全
app.add_middleware(
    CORSMiddleware,
    allow_origins=['http://localhost:5173', 'http://127.0.0.1:5173'],
    allow_methods=['*'],
    allow_headers=['*'],
)


def get_conn():
    """每请求新建 PG 连接（with psycopg2.connect 即自动 commit/close）。"""
    return psycopg2.connect(DSN)


@app.get('/api/stats')
def stats():
    """统计汇总：总量、今日新增、按域名分布、按日采集趋势。"""
    with get_conn() as conn, conn.cursor() as cur:
        # 一条 SQL 同时取总数和今日数（FILTER 条件聚合，PG 语法）
        cur.execute(
            'SELECT COUNT(*), '
            'COUNT(*) FILTER (WHERE crawled_at::date = CURRENT_DATE) '
            'FROM articles'
        )
        total, today = cur.fetchone()

        # 域名提取：url 形如 http://news.weather.com.cn/xxx → 先按 // 切取 host
        # 再按 / 切取第一段 = news.weather.com.cn（纯 SQL 字符串处理，无注入面）
        cur.execute(
            "SELECT split_part(split_part(url, '//', 2), '/', 1) AS domain, "
            'COUNT(*) FROM articles GROUP BY 1 ORDER BY 2 DESC LIMIT 10'
        )
        domains = [{'name': d, 'value': c} for d, c in cur.fetchall()]

        # 按日趋势：crawled_at::date 转日期 → 格式化 MM-DD 分组计数
        cur.execute(
            "SELECT to_char(crawled_at::date, 'MM-DD') AS day, COUNT(*) "
            'FROM articles GROUP BY 1 ORDER BY 1'
        )
        trend = [{'date': d, 'count': c} for d, c in cur.fetchall()]

    return {'total': total, 'today': today, 'domains': domains, 'trend': trend}


@app.get('/api/articles')
def articles(page: int = 1, size: int = 20):
    """文章分页列表（page 从 1 起；size 上限 100 防一次拉全表）。"""
    page = max(page, 1)               # 防御负数/零页码
    size = min(max(size, 1), 100)     # 防御超大 size

    offset = (page - 1) * size        # 偏移量 = 前面跳过的行数
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute('SELECT COUNT(*) FROM articles')
        total = cur.fetchone()[0]

        # LENGTH(content_md) 算正文字数，避免传输全文给列表页
        cur.execute(
            'SELECT id, title, url, published, LENGTH(content_md), '
            'to_char(crawled_at, \'YYYY-MM-DD HH24:MI\') '
            'FROM articles ORDER BY id DESC LIMIT %s OFFSET %s',
            (size, offset),
        )
        rows = cur.fetchall()

    items = [{
        'id': r[0], 'title': r[1] or '(无标题)', 'url': r[2],
        'published': r[3] or '-', 'content_len': r[4], 'crawled_at': r[5],
    } for r in rows]
    return {'total': total, 'items': items}


# 静态托管放最后注册（API 路由优先匹配）；html=True 让 / 回落到 index.html
_static_dir = os.path.join(os.path.dirname(__file__), 'static')
if os.path.isdir(_static_dir):
    app.mount('/', StaticFiles(directory=_static_dir, html=True), name='web')
