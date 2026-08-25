"""文章采集爬虫：读种子 URL → 下载 → trafilatura 提取正文 → 产出 ArticleItem。

聚焦采集（focused crawling）：不做自动链接发现，只爬种子清单里给出的
页面 —— 爬取边界永远可枚举（合规考虑，详见 README）。

trafilatura 对标 NewsCrawl 用的 GNE：都是"通用新闻正文抽取"，
输入整页 HTML，输出去掉导航/广告/侧栏后的干净正文（中文支持好）。

用法：
  scrapy crawl article                          # 用默认 seeds.txt
  SEEDS_FILE=my_seeds.txt scrapy crawl article  # 指定别的种子文件
"""

import hashlib
from typing import ClassVar

import scrapy
import trafilatura

from news_crawler.dupefilter import url_fingerprint
from news_crawler.items import ArticleItem


class ArticleSpider(scrapy.Spider):
    """通用文章采集：一个爬虫类吃所有白名单站点的文章页。"""

    name = 'article'   # 爬虫名（scrapy crawl article 按它启动）

    # ClassVar：Scrapy 惯例的类级配置字典（只读，不会实例改写）
    custom_settings: ClassVar[dict] = {
        # 本爬虫不跟随页面里的任何链接（聚焦模式，见模块注释）
        'DEPTH_LIMIT': 0,
    }

    async def start(self):
        """入口：读种子文件，逐个发出请求（空行/注释行跳过）。

        踩坑记录：Scrapy 2.13 起用 async start() 取代 start_requests()，
        2.18 已彻底移除旧方法 —— 只写 start_requests 会被静默忽略
        （一条请求都不发，爬虫"正常"空跑结束），必须用新 API。

        拆解 async def + yield = 异步生成器：框架 await 着逐个取请求，
        这里虽然全是同步逻辑，签名必须是 async 才会被调用。
        """
        seeds_file = self.settings['SEEDS_FILE']
        try:
            with open(seeds_file, encoding='utf-8') as f:
                seeds = [line.strip() for line in f
                         if line.strip() and not line.strip().startswith('#')]
        except FileNotFoundError:
            self.logger.error(f'种子文件不存在: {seeds_file}')
            return

        self.logger.info(f'从 {seeds_file} 载入 {len(seeds)} 个种子 URL')
        for url in seeds:
            # callback：响应回来后交给 parse 处理
            yield scrapy.Request(url, callback=self.parse)

    def parse(self, response):
        """解析响应：提取正文与元数据，产出 ArticleItem。

        trafilatura.extract 参数说明：
          output_format='markdown'  正文转成 Markdown（RAG 语料友好格式）
          include_comments=False    不要页面上"网友评论"区块
          favor_recall=True         宁多勿漏（正文召回优先，语料场景合适）
        """
        markdown = trafilatura.extract(
            response.text,
            output_format='markdown',
            include_comments=False,
            favor_recall=True,
        )

        # 正文为空或过短：导航页/登录墙/JS 渲染页，直接丢弃
        min_chars = self.settings['MIN_ARTICLE_CHARS']
        if not markdown or len(markdown) < min_chars:
            self.logger.debug(f'[丢弃] 无有效正文: {response.url}')
            return

        # 元数据（标题/发布日期）单独提取；提取失败时 as_dict 不可用，兜底空
        meta_obj = trafilatura.extract_metadata(response.text)
        meta = meta_obj.as_dict() if meta_obj else {}

        yield ArticleItem(
            url=response.url,
            url_fp=url_fingerprint(response.url),       # 请求级指纹（复用）
            title=(meta.get('title') or '').strip(),
            published=(meta.get('date') or '').strip(),
            content_md=markdown,
            # 内容级指纹：正文 SHA1 —— 同文不同链接只认第一份
            content_fp=hashlib.sha1(
                markdown.encode('utf-8')).hexdigest(),
        )
