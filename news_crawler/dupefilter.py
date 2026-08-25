"""请求级去重过滤器（Redis 版）：手写实现 scrapy-redis 的核心思想。

Scrapy 默认的 RFPDupeFilter 把指纹放在进程内存里：
  - 进程重启指纹全丢 → 断点续爬失效
  - 多进程各自一份内存 → 互相不知道对方爬过什么
生产项目（NewsCrawl 等）的解法：指纹集中存 Redis ——
  - 重启不丢（内存库但有持久化机制，且丢了也只是重复爬、可接受）
  - 多个爬虫进程共享同一份"已见清单"（这就是"分布式去重"）

原理只有一行：SADD 往集合里加元素，返回 1 表示"新元素"（没见过），
返回 0 表示"已存在"（见过 → 判定为重复请求，Scrapy 会丢弃它）。
"""

import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import redis
from scrapy.dupefilters import BaseDupeFilter


def normalize_url(url):
    """URL 规范化：让"同一页面"的不同写法归一成同一个地址。

    三件事：域名转小写、去掉 # 片段、剔除跟踪参数（utm_* 统计体系）。
    同一篇文章分享到不同平台会带不同 utm 参数，不归一就会重复采集。
    """
    parts = urlsplit(url)
    kept = [(k, v) for k, v in parse_qsl(parts.query)
            if k not in TRACKING_PARAMS]
    return urlunsplit((parts.scheme, parts.netloc.lower(),
                       parts.path or '/', urlencode(kept), ''))


def url_fingerprint(url):
    """URL 指纹：规范化后的 SHA1 十六进制摘要（定长 40 位）。"""
    return hashlib.sha1(normalize_url(url).encode('utf-8')).hexdigest()


# 跟踪参数黑名单（Google Analytics 统计体系的常见字段）
TRACKING_PARAMS = {'utm_source', 'utm_medium', 'utm_campaign',
                   'utm_term', 'utm_content'}


class RedisDupeFilter(BaseDupeFilter):
    """把请求指纹存进 Redis SET 的去重过滤器。"""

    def __init__(self, redis_url, key='dupefilter:urls'):
        # decode_responses=False：存取原始字节，指纹是 ASCII 字符串无碍
        self.redis = redis.from_url(redis_url, decode_responses=True)
        self.key = key   # Redis 里的集合名：按用途命名（dupefilter 域:类型）

    @classmethod
    def from_crawler(cls, crawler):
        """Scrapy 实例化组件的标准入口：从全局配置里取 Redis 地址。"""
        return cls(crawler.settings['REDIS_URL'])

    def request_seen(self, request):
        """核心方法：返回 True 表示该请求已处理过（将被丢弃）。

        拆解 SADD 语义：往集合添加元素并返回"实际新增数"——
          返回 1：集合里原本没有 → 新请求，登记后放行
          返回 0：集合里已经有了 → 重复请求，返回 True 让引擎丢弃
        一条命令原子完成"查 + 记"，不存在并发竞态窗口。
        """
        return self.redis.sadd(self.key, url_fingerprint(request.url)) == 0

    # ---- 以下两个方法是 Scrapy 的日志钩子，照抄返回 0 即可 ----

    def open(self):
        """开始一次爬取（本实现无需初始化，返回预计请求数 0）。"""
        return 0

    def close(self, reason):
        """爬取结束（无需清理：指纹要留给下次运行继续用 —— 断点续爬）。"""
