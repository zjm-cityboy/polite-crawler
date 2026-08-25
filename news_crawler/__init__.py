"""news_crawler：基于 Scrapy 的企业级新闻/文章采集工程。

架构分工（对标 NewsCrawl 生产项目）：
  Scrapy        采集框架（引擎/调度/下载/解析一条龙）
  Redis         双重去重（请求指纹 dupefilter + 正文指纹 pipeline）
  PostgreSQL    文章数据入库（业务存储）
  Kafka         采集结果向下游分发（消息管道）
  Scrapyd       爬虫守护进程（部署/定时/多任务管理）
  ScrapydWeb    网页端监控面板
"""
