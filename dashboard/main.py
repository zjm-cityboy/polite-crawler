"""看板后端：FastAPI 读 articles 表 + 触发爬取任务 + 托管前端构建产物。

四个接口（前端页面消费）：
  GET  /api/stats            统计汇总（总数/今日/域名分布/按日趋势）
  GET  /api/articles?page=&size=   文章分页列表
  POST /api/crawl            提交爬取需求：校验入口 URL → 触发 Scrapyd 任务
  GET  /api/jobs             任务列表（运行中/已完成，转发 Scrapyd API）

设计说明：
  - 看板是低频访问的展示层，直接"每请求新建连接"（连接池对它属于过度设计）
  - SQL 全部参数绑定；page/size 由 FastAPI 强制成 int（type hints 即校验）
  - 用户提交的 seed_url 必须过"协议 + 域名白名单"两道校验才转发给爬虫
    （看板不能变成"任意指挥爬虫"的口子 —— 与爬虫侧中间件同一套白名单）
  - 调 Scrapyd 用标准库 urllib（不为此引入 requests/httpx 依赖）
  - 生产模式：本服务同时托管 frontend/dist 静态文件（前后端同源，无跨域）
"""

import json
import os
from urllib import request as urllib_request
from urllib.parse import urlsplit

import psycopg2
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

DSN = os.environ.get(
    'CRAWLER_DSN',
    'postgresql://postgres:postgres@localhost:5433/crawler',
)

# Scrapyd 地址：本机直跑用 localhost:6800，容器内由 compose 注入 http://scrapyd:6800
SCRAPYD_URL = os.environ.get('SCRAPYD_URL', 'http://localhost:6800')

# 域名白名单：与爬虫侧 settings.ALLOWED_HOSTS 同一份（compose 注入保持一致）
ALLOWED_HOSTS = {
    h.strip() for h in os.environ.get(
        'ALLOWED_HOSTS',
        'www.weather.com.cn,news.weather.com.cn,p.weather.com.cn',
    ).split(',') if h.strip()
}

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


# ---------------- 爬取任务：提交与查询 ----------------


class CrawlRequest(BaseModel):
    """提交爬取的请求体：{ "url": "http://..." }（pydantic 负责结构校验）"""

    url: str


def scrapyd_api(path, data=None):
    """调 Scrapyd HTTP API 并返回 json（标准库 urllib 实现，零新依赖）。

    data 为 None 走 GET，否则 POST（表单编码）。
    目标地址是环境变量注入的内部 Scrapyd（http/https 且非外部用户可控）。
    """
    url = f'{SCRAPYD_URL}{path}'
    body = None
    headers = {}
    if data is not None:
        # 表单编码：k=v&k2=v2（值是简单 ASCII 参数，无需完整 urlencode 库）
        body = '&'.join(f'{k}={v}' for k, v in data.items()).encode()
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    req = urllib_request.Request(url, data=body, headers=headers)
    with urllib_request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


@app.post('/api/crawl')
def start_crawl(req: CrawlRequest):
    """提交爬取需求：校验入口 URL → 触发 Scrapyd 任务，返回 jobid。

    两道校验（与爬虫侧中间件同口径，看板不是任意指挥爬虫的口子）：
      1. 协议只认 http/https
      2. 域名必须在白名单内（未登记的站点直接 400）
    """
    parts = urlsplit(req.url.strip())
    if parts.scheme not in ('http', 'https'):
        raise HTTPException(400, '只支持 http/https 链接')
    host = parts.hostname or ''
    if host not in ALLOWED_HOSTS:
        raise HTTPException(
            400,
            f'域名 {host} 不在采集白名单内（白名单：'
            f'{"、".join(sorted(ALLOWED_HOSTS))}）',
        )

    # 触发 Scrapyd：-a seed_url=xxx 传给 spider 的 self.seed_url
    result = scrapyd_api('/schedule.json', {
        'project': 'news_crawler',
        'spider': 'article',
        'seed_url': req.url.strip(),
    })
    if result.get('status') != 'ok':
        raise HTTPException(502, f'Scrapyd 调度失败: {result}')
    return {'jobid': result['jobid'], 'status': 'ok'}


@app.get('/api/jobs')
def jobs():
    """任务列表：转发 Scrapyd listjobs（前端轮询展示运行状态）。"""
    result = scrapyd_api('/listjobs.json?project=news_crawler')
    # 只保留前端需要的字段，finished 取最近 5 条（倒序截断）
    def brief(j):
        return {
            'id': j['id'][:8],
            'spider': j.get('spider', ''),
            'start_time': j.get('start_time', '')[:19],
            'end_time': j.get('end_time', '')[:19],
        }
    return {
        'pending': [brief(j) for j in result.get('pending', [])],
        'running': [brief(j) for j in result.get('running', [])],
        'finished': [brief(j) for j in result.get('finished', [])[-5:]][::-1],
    }


@app.get('/api/article/{article_id}')
def article_detail(article_id: int):
    """单篇正文：前端"查看正文"弹窗按需加载（列表不传全文，省带宽）。"""
    with get_conn() as conn, conn.cursor() as cur:
        # 参数绑定；只查一篇主键行
        cur.execute(
            'SELECT id, title, url, published, content_md, '
            'to_char(crawled_at, \'YYYY-MM-DD HH24:MI\') '
            'FROM articles WHERE id = %s',
            (article_id,),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, f'文章不存在: {article_id}')
    return {
        'id': row[0], 'title': row[1] or '(无标题)', 'url': row[2],
        'published': row[3] or '-', 'content_md': row[4],
        'crawled_at': row[5],
    }


# 静态托管放最后注册（API 路由优先匹配）；html=True 让 / 回落到 index.html
_static_dir = os.path.join(os.path.dirname(__file__), 'static')
if os.path.isdir(_static_dir):
    app.mount('/', StaticFiles(directory=_static_dir, html=True), name='web')
