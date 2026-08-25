"""数据条目定义：一篇文章 = 一个 ArticleItem（在管道间流转的"货物"）。

拆解：scrapy.Item 像一个带类型校验的字典——
字段先声明后使用，写错字段名会在运行时立刻报错（普通 dict 不会）。
"""

import scrapy


class ArticleItem(scrapy.Item):
    url = scrapy.Field()          # 最终响应地址
    url_fp = scrapy.Field()       # URL 指纹（SHA1 40 位）：请求级去重用
    title = scrapy.Field()        # 标题（trafilatura 元数据提取）
    published = scrapy.Field()    # 原文发布日期（字符串，来源格式不一）
    content_md = scrapy.Field()   # 正文（Markdown，已去导航/广告/侧栏）
    content_fp = scrapy.Field()   # 正文指纹（SHA1 40 位）：内容级去重用
