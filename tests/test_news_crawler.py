"""离线单元测试：不联网、不依赖 Redis/PG/Kafka 服务（外部依赖全部打桩）。

运行：python -m pytest tests/ -v
覆盖：URL 规范化指纹 / 合规中间件三连检 / 正文解析 / 内容去重管道。
"""

import sys
from pathlib import Path

import pytest

# 把项目根目录加入模块搜索路径（无需 pip install -e 即可导入工程）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scrapy.exceptions import IgnoreRequest

from news_crawler.dupefilter import (
    url_fingerprint,
)
from news_crawler.middlewares import ComplianceMiddleware

# ---------------- URL 规范化与指纹 ----------------

class TestUrlFingerprint:
    def test_tracking_params_removed(self):
        """utm 跟踪参数剔除后，同一页面不同分享链接指纹相同"""
        a = 'https://www.weather.com.cn/news/1.html?utm_source=weibo'
        b = 'https://www.weather.com.cn/news/1.html?utm_source=weixin'
        assert url_fingerprint(a) == url_fingerprint(b)

    def test_host_case_and_fragment(self):
        """域名大小写、# 片段不影响指纹"""
        a = 'https://WWW.Weather.com.cn/news/1.html#comment'
        b = 'https://www.weather.com.cn/news/1.html'
        assert url_fingerprint(a) == url_fingerprint(b)

    def test_different_paths_different_fp(self):
        assert url_fingerprint('https://a.com/x') != url_fingerprint(
            'https://a.com/y')

    def test_fingerprint_length(self):
        """SHA1 十六进制 = 定长 40 位"""
        assert len(url_fingerprint('https://a.com/x')) == 40


# ---------------- 合规中间件 ----------------

class TestComplianceMiddleware:
    def make_mw(self, hosts):
        return ComplianceMiddleware(set(hosts))

    def test_reject_private_ip(self):
        """私网/环回地址请求被 SSRF 防护拦截（字面 IP 不触发联网 DNS）"""
        mw = self.make_mw({'127.0.0.1', '192.168.1.1', '10.1.1.1'})
        for url in ('http://127.0.0.1:8000/x',
                    'http://192.168.1.1/admin',
                    'http://10.1.1.1/internal'):
            with pytest.raises(IgnoreRequest):
                mw.process_request(self._fake_req(url))

    def test_reject_non_http_scheme(self):
        """file://、ftp:// 协议直接拒绝"""
        mw = self.make_mw({'example.com'})
        for url in ('file:///etc/passwd', 'ftp://example.com/x'):
            with pytest.raises(IgnoreRequest):
                mw.process_request(self._fake_req(url))

    def test_reject_host_not_in_whitelist(self):
        """白名单外的域名拒绝（_resolve 打桩避免真实 DNS）"""
        mw = self.make_mw({'www.weather.com.cn'})
        mw._resolve = lambda host: '1.2.3.4'   # 打桩：假装解析到公网 IP
        with pytest.raises(IgnoreRequest):
            mw.process_request(
                self._fake_req('https://evil.com/x'))

    def test_pass_whitelisted_public_host(self):
        """白名单内 + 公网 IP → 放行（返回 None）"""
        mw = self.make_mw({'www.weather.com.cn'})
        mw._resolve = lambda host: '1.2.3.4'
        result = mw.process_request(
            self._fake_req('https://www.weather.com.cn/news/1.html'))
        assert result is None

    @staticmethod
    def _fake_req(url):
        """最小可用的 Request 替身（只用得到 .url 属性）"""
        class FakeRequest:
            pass
        req = FakeRequest()
        req.url = url
        return req


# ---------------- 正文解析（trafilatura 离线） ----------------

class TestParse:
    @staticmethod
    def _make_spider():
        """实例化 spider 并手动绑定 settings（真实运行时由 Scrapy 注入）"""
        from scrapy.settings import Settings

        from news_crawler.spiders.article_spider import ArticleSpider
        spider = ArticleSpider()
        spider.settings = Settings({
            'MIN_ARTICLE_CHARS': 50,
            'FOLLOW_LINKS': True,   # 链接发现开启（真爬虫模式）
        })
        return spider

    @staticmethod
    def _fake_response(url, text):
        """用 Scrapy 真实 HtmlResponse：自带 css 选择器（链接发现依赖它）"""
        from scrapy.http import HtmlResponse
        return HtmlResponse(url=url, body=text.encode('utf-8'),
                            encoding='utf-8')

    def test_extract_article_and_fp(self):
        """有正文页面 → 产出条目；两个 URL 同正文 → 内容指纹相同"""
        # 正文长度需超过 MIN_ARTICLE_CHARS（50 字）才会被采集
        html = ('<html><body><article><h1>台风预警升级</h1>'
                '<p>中央气象台今日六时发布台风橙色预警，'
                '预计未来两天东南沿海将出现强风雨天气过程，'
                '部分海域阵风可达十三级，沿海各地需做好防风防潮准备，'
                '海上作业渔船应尽快回港避风，公众请减少外出。</p>'
                '</article></body></html>')
        spider = self._make_spider()

        items = list(spider.parse(self._fake_response(
            'https://www.weather.com.cn/news/a.html', html)))
        assert len(items) == 1
        item = items[0]
        assert item['title'] == '台风预警升级'
        assert '台风橙色预警' in item['content_md']
        assert len(item['content_fp']) == 40

        # 同文不同链接：内容指纹一致（内容级去重的判定依据）
        items2 = list(spider.parse(self._fake_response(
            'https://www.weather.com.cn/news/b.html', html)))
        assert items2[0]['content_fp'] == item['content_fp']

    def test_drop_nav_page(self):
        """无有效正文的导航页 → 不产出条目（也没有可跟随的链接）"""
        html = '<html><body><ul><li>首页</li><li>新闻</li></ul></body></html>'
        spider = self._make_spider()
        assert list(spider.parse(self._fake_response(
            'https://www.weather.com.cn/', html))) == []

    def test_link_discovery(self):
        """列表页链接发现：只跟文章模式的链接，页内重复与栏目不跟"""
        from scrapy import Request
        # 列表页：2 个文章链接（一个绝对、一个相对）、1 个重复、
        # 1 个栏目链接、1 个外站文章 —— 预期产出 3 个文章 Request
        # （外站那个 parse 层会放行：符合文章模式；真实运行时由
        #   OffsiteMiddleware/合规中间件在请求层拦下 —— 职责分离）
        html = """
        <html><body>
        <a href="http://news.weather.com.cn/2026/08/4771293.shtml">文章A</a>
        <a href="/2026/08/4771531.shtml">文章B(相对链接)</a>
        <a href="/2026/08/4771293.shtml">文章A又出现一次</a>
        <a href="/news/">新闻栏目(非文章模式)</a>
        <a href="http://evil.com/2026/08/666.shtml">外站诱饵</a>
        </body></html>
        """
        spider = self._make_spider()
        results = list(spider.parse(self._fake_response(
            'http://news.weather.com.cn/index.shtml', html)))

        # 全部产出是 Request（列表页无正文）
        assert all(isinstance(r, Request) for r in results)
        urls = [r.url for r in results]
        # 3 个：文章A + 文章B + 外站诱饵（重复的 A 与栏目页被过滤）
        assert len(urls) == 3, f'应产出 3 个请求，实际 {urls}'
        # 相对链接被补成绝对地址
        assert 'http://news.weather.com.cn/2026/08/4771531.shtml' in urls
        # 页内重复（文章A 第二次出现）没有多产出
        assert urls.count('http://news.weather.com.cn/2026/08/4771293.shtml') == 1
        # 栏目链接（不符合文章模式）没被跟随
        assert 'http://news.weather.com.cn/news/' not in urls


# ---------------- 内容去重管道（Redis 打桩） ----------------

class FakeRedis:
    """Redis SET 的内存替身：sadd 返回值语义与真 Redis 完全一致。"""

    def __init__(self):
        self._set = set()

    def sadd(self, key, value):
        # 真实语义：返回实际新增数（1=新，0=已存在）
        if value in self._set:
            return 0
        self._set.add(value)
        return 1


class TestRedisDedupePipeline:
    def make_pipeline(self):
        from news_crawler.pipelines import RedisDedupePipeline
        pipe = RedisDedupePipeline('redis://fake')
        pipe.redis = FakeRedis()      # 打桩：不连真实 Redis
        return pipe

    @staticmethod
    def _item(fp):
        return {'url': 'https://a.com/x', 'content_fp': fp}

    def test_first_passes_second_drops(self):
        pipe = self.make_pipeline()
                # 第一份放行
        assert pipe.process_item(self._item('fp-1')) is not None
        # 同指纹第二份被 DropItem 拦下
        from scrapy.exceptions import DropItem
        with pytest.raises(DropItem):
            pipe.process_item(self._item('fp-1'))
        # 不同指纹正常放行
        assert pipe.process_item(self._item('fp-2')) is not None
