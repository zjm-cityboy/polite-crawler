"""管道链：采集到的 ArticleItem 依次流过三个管道（对标 NewsCrawl 的
"前处理 → 过滤清洗 → 入库 MySQL → 推 Kafka"分工）。

执行顺序由 settings.py 的数字决定（100 → 200 → 300）：
  RedisDedupePipeline  100  正文指纹去重（重复的直接丢，不进后续管道）
  PostgresPipeline     200  文章入库 PostgreSQL（业务存储，数据库级兜底去重）
  KafkaPipeline        300  推送到 Kafka articles 主题（下游分发）

钩子签名说明：Scrapy 2.13+ 新签名不再传 spider 参数
（open_spider/process_item/close_spider 均只收自身数据），日志用标准
logging 模块输出 —— 与框架版本演进保持一致。
"""

import json
import logging

import redis
from kafka import KafkaProducer
from scrapy.exceptions import DropItem

from news_crawler.db import DDL_ARTICLES, pg_conn

logger = logging.getLogger(__name__)


class QualityFilterPipeline:
    """质量过滤管道（管道链第一位）：拦截低信息量页面。

    实测的两类垃圾（2026-08 气象站源数据诊断）：
      404 错误页：正文是"非常抱歉，网页无法访问"提示语（154 字）
      图片频道页：标题以"-图片频道"结尾，正文只是图注（约 420 字）
    与"短资讯"的区分：真资讯（如 417 字的降雨预报）有信息量，
    不能只按字数一刀切 —— 标题/URL 模式黑名单 + 字数下限组合判断。
    """

    # 标题黑名单：命中即丢（图集/视频/直播页的文字信息量低）
    TITLE_BLACKLIST = ('图片频道', '视频', '直播', '专题')

    def __init__(self, min_chars):
        self.min_chars = min_chars
        self.dropped = 0   # 本次运行拦截数（统计用）

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler.settings['QUALITY_MIN_CHARS'])

    def process_item(self, item):
        title = item['title']
        # 规则 1：标题黑名单（"-图片频道"等后缀）
        if any(word in title for word in self.TITLE_BLACKLIST):
            self.dropped += 1
            raise DropItem(f'[低质·标题黑名单] {title}')
        # 规则 2：URL 命中 error（404 页等站点错误模板）
        if 'error' in item['url']:
            self.dropped += 1
            raise DropItem(f'[低质·错误页] {item["url"]}')
        # 规则 3：字数下限（拦截错误提示语等超短文本）
        if len(item['content_md']) < self.min_chars:
            self.dropped += 1
            raise DropItem(f'[低质·正文过短] {len(item["content_md"])}字 {title}')
        return item

    def close_spider(self):
        logger.info('[统计] 质量过滤拦截低质页面 %d 条', self.dropped)


class RedisDedupePipeline:
    """内容级去重：同一篇文章换了链接/被转载，只放行第一份。

    与请求级去重（dupefilter）的分工：
      请求级管"这个 URL 爬没爬过"——针对链接
      内容级管"这篇文章存没存过"——针对正文
    实现：正文 SHA1 指纹 SADD 进 Redis 集合，返回 0 = 已存在 = 重复。
    """

    def __init__(self, redis_url):
        self.redis_url = redis_url
        self.key = 'dupefilter:content'   # 与请求级指纹分开两个集合
        self.seen_dups = 0                # 本次运行拦截的重复数（统计用）

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler.settings['REDIS_URL'])

    def open_spider(self):
        # 爬虫启动时建立 Redis 连接（decode_responses=True：字节→字符串）
        self.redis = redis.from_url(self.redis_url, decode_responses=True)

    def process_item(self, item):
        if self.redis.sadd(self.key, item['content_fp']) == 0:
            self.seen_dups += 1
            # DropItem：Scrapy 的标准丢弃信号，后续管道不再收到该条目
            raise DropItem(f'[内容重复] {item["url"]}')
        return item   # 放行给下一个管道

    def close_spider(self):
        logger.info('[统计] 内容级去重拦截重复 %d 条', self.seen_dups)


class PostgresPipeline:
    """文章入库 PostgreSQL。

    SQL 全部参数绑定（%s 占位符，值由驱动安全转义，杜绝注入）。
    content_fp 加了 UNIQUE 约束：即使 Redis 指纹全丢导致放行了重复内容，
    数据库这边也会 ON CONFLICT DO NOTHING 兜底挡住 —— 双保险。
    """

    insert_sql = ('INSERT INTO articles '
                  '(url, url_fp, title, published, content_md, content_fp) '
                  'VALUES (%s, %s, %s, %s, %s, %s) '
                  'ON CONFLICT (content_fp) DO NOTHING')

    def __init__(self, dsn):
        self.dsn = dsn
        self.inserted = 0   # 本次运行实际入库数（统计用）

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler.settings['CRAWLER_DSN'])

    def open_spider(self):
        # 启动时建表（幂等）：保证任何环境跑起来表都存在
        with pg_conn(self.dsn) as conn, conn.cursor() as cur:
            cur.execute(DDL_ARTICLES)

    def process_item(self, item):
        with pg_conn(self.dsn) as conn, conn.cursor() as cur:
            # 拆解 rowcount：1=真正插入；0=指纹冲突被 ON CONFLICT 跳过
            cur.execute(self.insert_sql, (
                item['url'], item['url_fp'], item['title'],
                item['published'], item['content_md'], item['content_fp'],
            ))
            self.inserted += cur.rowcount
        return item   # 继续流向 Kafka 管道

    def close_spider(self):
        logger.info('[统计] PostgreSQL 入库 %d 条', self.inserted)


class KafkaPipeline:
    """采集结果推送到 Kafka：把"爬到的数据"广播给任意多个下游系统。

    为什么入库了还要推 Kafka：PG 是"本系统的存储"，Kafka 是"对外的分发口"
    —— 下游（分析服务、RAG 入库程序、告警系统）各自订阅同一主题即可，
    爬虫不需要认识任何一个下游（生产者/消费者解耦，NewsCrawl 同款用法）。
    """

    def __init__(self, bootstrap, topic):
        self.bootstrap = bootstrap
        self.topic = topic
        self.sent = 0   # 本次运行推送数（统计用）

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler.settings['KAFKA_BOOTSTRAP'],
                   crawler.settings['KAFKA_TOPIC'])

    def open_spider(self):
        # value_serializer：发消息前自动把 dict → JSON 字节串
        # api_version 显式指定：避免 kafka-python 自动协商失败
        #（不指定时首次 send 会报 "Topic not found in cluster metadata" 告警）
        self.producer = KafkaProducer(
            bootstrap_servers=self.bootstrap,
            api_version=(3, 5, 0),
            value_serializer=lambda v: json.dumps(v, ensure_ascii=False)
            .encode('utf-8'),
        )

    def process_item(self, item):
        # 消息体只带元数据 + 指纹，不带全文（下游要全文可按 url_fp 回 PG 查，
        # 避免大正文在消息队列里反复搬运 —— 生产环境的常见瘦身做法）
        message = {
            'url': item['url'],
            'url_fp': item['url_fp'],
            'title': item['title'],
            'published': item['published'],
            'content_fp': item['content_fp'],
        }
        try:
            # send 是异步的：先入本地缓冲区，由后台线程批量发出（高吞吐关键）
            self.producer.send(self.topic, message)
            self.sent += 1
        except Exception as e:   # noqa: BLE001 —— Kafka 故障不阻断入库主流程
            # 推送失败只记日志：PG 已入库，数据不丢；Kafka 恢复后可重爬补推
            logger.warning('[Kafka] 推送失败（不影响入库）: %s', e)
        return item

    def close_spider(self):
        # flush：把缓冲区里的消息真正发完再退出（否则进程结束消息会丢）
        if self.producer:
            self.producer.flush(timeout=10)
            self.producer.close()
        logger.info('[统计] Kafka 推送 %d 条', self.sent)
