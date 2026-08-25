"""文章采集爬虫：入口页自动发现链接 → 逐篇提取正文（真正的爬虫行为）。

两种页面一个 parse 通吃（Scrapy 经典模式）：
  列表页/频道页 → 无正文，但能挖出文章链接 → yield 新 Request 继续爬
  文章详情页   → trafilatura 提取正文 → yield ArticleItem 入管道

自动发现 ≠ 失控爬取，四重刹车缺一不可（详见 README「合规设计」）：
  1. 白名单域：ALLOWED_HOSTS 之外的域名一个请求都不发（合规中间件）
  2. URL 模式：只跟随符合"文章页"形状的链接（正则白名单，列表/广告不跟）
  3. 深度限制：DEPTH_LIMIT 封顶跟随跳数（防无限级联）
  4. 数量熔断：CLOSESPIDER_ITEM_COUNT 采够即自动停（防一夜爬光整站）

用法：
  scrapy crawl article                          # 用默认 seeds.txt
  SEEDS_FILE=my_seeds.txt scrapy crawl article  # 指定别的种子文件
种子给"入口页"即可（频道首页/列表页），spider 自己发现文章。
"""

import hashlib
import re
from typing import ClassVar
from urllib.parse import urljoin

import scrapy
import trafilatura

from news_crawler.dupefilter import url_fingerprint
from news_crawler.items import ArticleItem

# 文章 URL 模式（正则白名单）：形如 /2026/08/4771293.shtml 的详情页地址
# 只跟这个形状的链接 —— 栏目页、专题页、广告位即使出现也不跟随
ARTICLE_URL_RE = re.compile(r'/\d{4}/\d{2}/\d+\.shtml?$')


class ArticleSpider(scrapy.Spider):
    """通用文章采集：链接发现 + 正文提取双角色。"""

    name = 'article'   # 爬虫名（scrapy crawl article 按它启动）

    # 域名约束（Scrapy 内置 OffsiteMiddleware 用）：发现的链接只跟这些域
    # 与 settings 的 ALLOWED_HOSTS 保持一致口径，双保险
    allowed_domains: ClassVar[list] = ['weather.com.cn']

    async def start(self):
        """入口：优先用调用方传入的 seed_url 参数，否则读种子文件。

        踩坑记录：Scrapy 2.13 起用 async start() 取代 start_requests()，
        2.18 已彻底移除旧方法 —— 只写 start_requests 会被静默忽略
        （一条请求都不发，爬虫"正常"空跑结束），必须用新 API。

        spider 参数是 Scrapy 的标准能力：scrapyd 触发时 -a seed_url=xxx
        传值，spider 里 self.seed_url 取到（看板"提交爬取"按钮走这条路）；
        命令行也能用：scrapy crawl article -a seed_url=http://...
        """
        # 未传参数时 self.seed_url 默认 None（Scrapy 基类自动注入）
        if getattr(self, 'seed_url', None):
            seeds = [self.seed_url.strip()]
            self.logger.info(f'使用调用方传入的种子: {seeds[0]}')
        else:
            seeds_file = self.settings['SEEDS_FILE']
            try:
                # 种子文件只有几行（微秒级读取），阻塞开销可忽略，
                # 不为此引入线程池跳转（务实取舍）
                with open(seeds_file, encoding='utf-8') as f:  # noqa: ASYNC230
                    seeds = [line.strip() for line in f
                             if line.strip() and not line.strip().startswith('#')]
            except FileNotFoundError:
                self.logger.error(f'种子文件不存在: {seeds_file}')
                return
            self.logger.info(f'从 {seeds_file} 载入 {len(seeds)} 个种子 URL')

        for url in seeds:
            # callback 省略：默认回调就是 parse（列表页和文章页统一处理）
            yield scrapy.Request(url)

    def parse(self, response):
        """双角色解析：先试提正文（文章页），再挖链接（列表页）。

        一个响应可以同时产出 item 和新 Request：文章页里的"相关阅读"
        链接也会被发现（受深度限制约束，不会无限扩散）。
        """
        # ---- 角色 A：正文提取（trafilatura 对标 NewsCrawl 用的 GNE） ----
        markdown = trafilatura.extract(
            response.text,
            output_format='markdown',
            include_comments=False,
            favor_recall=True,
        )
        min_chars = self.settings['MIN_ARTICLE_CHARS']
        if markdown and len(markdown) >= min_chars:
            meta_obj = trafilatura.extract_metadata(response.text)
            meta = meta_obj.as_dict() if meta_obj else {}

            yield ArticleItem(
                url=response.url,
                url_fp=url_fingerprint(response.url),
                title=(meta.get('title') or '').strip(),
                published=(meta.get('date') or '').strip(),
                content_md=markdown,
                # 内容级指纹：正文 SHA1 —— 同文不同链接只认第一份
                content_fp=hashlib.sha1(
                    markdown.encode('utf-8')).hexdigest(),
            )
        else:
            self.logger.debug(f'[无正文·当列表页处理] {response.url}')

        # ---- 角色 B：链接发现（真爬虫的灵魂） ----
        if not self.settings.getbool('FOLLOW_LINKS', True):
            return   # 开关关掉：退化为纯聚焦采集模式

        # response.css 是 Scrapy 的选择器：取出页面全部 <a href="...">
        seen_in_page = set()   # 页内去重：同一篇文章链接出现多次只发一次请求
        for href in response.css('a::attr(href)').getall():
            # urljoin 把相对链接（/2026/08/x.shtml）补成完整绝对地址
            url = urljoin(response.url, href)

            # 模式过滤：只跟"文章形状"的链接（刹车 2）
            if not ARTICLE_URL_RE.search(url):
                continue
            # 页内去重 + 已产出过本页 URL 跳过
            if url in seen_in_page:
                continue
            seen_in_page.add(url)

            # yield 新请求：引擎把它交给调度器（Redis 去重后再决定发不发），
            # 响应回来仍走 parse —— 链条就这样一环扣一环自动展开
            yield scrapy.Request(url)
