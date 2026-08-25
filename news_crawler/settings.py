"""Scrapy 全局配置：合规、限速、重试、去重、管道、外部服务地址。

对比自研版（v1 脚本）的启示：下面一大半配置（robots/限速/重试/UA/去重）
在自研版里都要手写几十行，Scrapy 内置成开关 —— 这就是框架的价值。
"""

import os

# ---------------- 基础 ----------------

BOT_NAME = 'news_crawler'
SPIDER_MODULES = ['news_crawler.spiders']   # Scrapy 从这里发现爬虫类
NEWSPIDER_MODULE = 'news_crawler.spiders'

# 自报身份：礼貌爬虫应在 UA 里亮明身份（robots 协议精神）
# 中间件会用浏览器 UA 池轮换覆盖它（详见 middlewares.py 的取舍说明）
USER_AGENT = 'polite-crawler/1.0 (+learning project)'

# ---------------- 合规（合法性优先于一切） ----------------

# 强制遵守 robots.txt：目标站声明禁止的路径直接不请求
# 这是法律调研结论的技术落地（详见 README「合规设计」）
ROBOTSTXT_OBEY = True

# 站点白名单：不在名单里的域名一律不出请求（合规中间件强制执行）
# 逗号分隔，可用环境变量覆盖（容器内注入同款）
ALLOWED_HOSTS = {
    host.strip() for host in
    os.environ.get('ALLOWED_HOSTS',
                   'www.weather.com.cn,news.weather.com.cn,'
                   'p.weather.com.cn').split(',')
    if host.strip()
}

# ---------------- 限速：礼貌采集（AutoThrottle 自动限速扩展） ----------------

# AutoThrottle：按目标服务器的实际响应延迟动态调节速度——
# 服务器变慢我们自动放慢，不硬冲（对应自研版手写的"最小间隔+抖动"）
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 1.0        # 起始下载间隔（秒）
AUTOTHROTTLE_MAX_DELAY = 10.0         # 服务器变慢时间隔的上限（秒）
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0  # 每站点同时进行的请求数：1=串行最礼貌

DOWNLOAD_DELAY = 1                     # 基础下载间隔（秒）
RANDOMIZE_DOWNLOAD_DELAY = True        # 间隔随机化为 0.5~1.5 倍：去机器特征
CONCURRENT_REQUESTS = 2                # 全局并发请求上限
CONCURRENT_REQUESTS_PER_DOMAIN = 1     # 每域名并发=1：对单站绝不齐射

DOWNLOAD_TIMEOUT = 10                  # 单请求 10 秒无响应放弃
RETRY_TIMES = 2                        # 失败重试 2 次（Scrapy 重试中间件）
# 429(请求过多)/403(被拒) 交给重试中间件退避重发；500 系是服务器问题
RETRY_HTTP_CODES = [429, 403, 500, 502, 503, 504]

# ---------------- 去重：Redis 版（替代默认的内存去重） ----------------

# 默认 RFPDupeFilter 把指纹放内存，重启即失效；换 Redis 版实现跨重启、
# 跨进程持久去重（scrapy-redis 的核心思想，本工程手写 60 行实现）
DUPEFILTER_CLASS = 'news_crawler.dupefilter.RedisDupeFilter'

# ---------------- 管道链：按数字从小到大依次执行 ----------------

ITEM_PIPELINES = {
    'news_crawler.pipelines.QualityFilterPipeline': 50,  # 0. 质量过滤（拦垃圾）
    'news_crawler.pipelines.RedisDedupePipeline': 100,   # 1. 正文指纹去重
    'news_crawler.pipelines.PostgresPipeline': 200,      # 2. 文章入库 PG
    'news_crawler.pipelines.KafkaPipeline': 300,         # 3. 推 Kafka 给下游
}

# 质量过滤参数：正文低于 300 字丢弃（实测 404 错误页 154 字、
# 正常短资讯 417 字 —— 300 是分界线；图片频道另由标题黑名单拦截）
QUALITY_MIN_CHARS = 300

# ---------------- 中间件链（下载侧） ----------------

DOWNLOADER_MIDDLEWARES = {
    # 数字越小越先执行：合规检查放最前面，非法请求第一时间拦下
    'news_crawler.middlewares.ComplianceMiddleware': 10,
    'news_crawler.middlewares.RandomUserAgentMiddleware': 400,
}

# ---------------- 链接发现（真爬虫模式）与四重刹车 ----------------

# 链接发现总开关：True=入口页自动发现文章链接继续爬（真爬虫行为）；
# False=只爬种子清单本身（聚焦采集，退化模式）
# 自动发现不等于失控：白名单域(中间件) + URL 模式(spider 正则)
# + 深度限制 + 数量熔断，四重刹车缺一不可
FOLLOW_LINKS = True

# 刹车 3 深度限制：从种子页算起最多跟随 2 跳
# （入口页→文章页=1 跳；文章页"相关阅读"→下一篇=2 跳，到此为止）
DEPTH_LIMIT = 2

# 刹车 4 数量熔断：本次运行采满 30 篇自动关闭爬虫（防一夜爬光整站）
CLOSESPIDER_ITEM_COUNT = 30

# 兜底刹车：总请求数上限（含列表页），200 个请求必停
CLOSESPIDER_PAGECOUNT = 200

# ---------------- 外部服务地址（环境变量区分本机/容器） ----------------

# 本机直跑（compose 暴露的端口）与容器内跑（服务名寻址）用不同默认值
REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
CRAWLER_DSN = os.environ.get(
    'CRAWLER_DSN',
    'postgresql://postgres:postgres@localhost:5433/crawler',
)
KAFKA_BOOTSTRAP = os.environ.get('KAFKA_BOOTSTRAP', 'localhost:9092')
KAFKA_TOPIC = os.environ.get('KAFKA_TOPIC', 'articles')

# 种子文件路径（每行一个 URL，# 开头为注释行）
SEEDS_FILE = os.environ.get('SEEDS_FILE', 'seeds.txt')

# 最短正文长度（字符）：低于按"无有效内容"丢弃（导航页/登录墙）
MIN_ARTICLE_CHARS = 50

# 日志级别
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')

# 不遵守 telnet 控制端口（生产惯例：关闭）
TELNETCONSOLE_ENABLED = False
