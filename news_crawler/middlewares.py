"""下载中间件：请求发出前的两道处理（对标自研版的合规层 + UA 轮换）。

执行顺序由 settings.py 里的数字决定：合规检查(10) → … → UA 轮换(400)。
"""

import ipaddress
import random
import socket
from typing import ClassVar
from urllib.parse import urlsplit

from scrapy.exceptions import IgnoreRequest


class ComplianceMiddleware:
    """合规中间件：所有请求的第一道关卡（数字最小 = 最先执行）。

    三连检（全部通过才放行）：
      1. 协议白名单：只允许 http/https
      2. 站点白名单：只爬 ALLOWED_HOSTS 登记过的域名（边界可控、可审计）
      3. SSRF 防护：域名解析出的 IP 若是私网/环回/保留地址则拒绝
         （防"服务端请求伪造"：恶意 URL 借爬虫之手探测内网服务）
    robots.txt 由 Scrapy 内置的 RobotsTxtMiddleware 强制执行
    （settings 里 ROBOTSTXT_OBEY = True），不在这里重复实现。

    不通过的处理：抛 IgnoreRequest —— Scrapy 会丢弃该请求并记录日志，
    不会让它走到网络层。
    """

    def __init__(self, allowed_hosts):
        self.allowed_hosts = allowed_hosts

    @classmethod
    def from_crawler(cls, crawler):
        """Scrapy 组件标准工厂：从全局配置取白名单。"""
        return cls(crawler.settings['ALLOWED_HOSTS'])

    def process_request(self, request):
        """每个请求发出前都会经过这里（Scrapy 2.13+ 新签名：无 spider 参数）。

        返回 None = 继续走后续流程。
        """
        parts = urlsplit(request.url)

        # 第 1 道：协议
        if parts.scheme not in ('http', 'https'):
            raise IgnoreRequest(f'[拦截] 协议不允许: {request.url}')

        # 第 2 道：站点白名单
        host = parts.hostname or ''
        if host not in self.allowed_hosts:
            raise IgnoreRequest(f'[拦截] 域名不在白名单: {host}')

        # 第 3 道：SSRF 防护（解析 IP 检查网段）
        ip = self._resolve(host)
        if ip is None:
            raise IgnoreRequest(f'[拦截] 域名解析失败: {host}')
        if self._is_blocked_ip(ip):
            raise IgnoreRequest(f'[拦截] 内网/保留地址: {ip}')


    @staticmethod
    def _resolve(host):
        """DNS 解析：域名 → IP 字符串；失败返回 None。

        host 本身是 IP 字面量（如 127.0.0.1）时系统直接返回，不联网。
        """
        try:
            infos = socket.getaddrinfo(host, None)
            return infos[0][4][0]
        except OSError:
            return None

    @staticmethod
    def _is_blocked_ip(ip_str):
        """IP 是否属于内网/环回/保留网段 —— SSRF 防护核心。"""
        ip = ipaddress.ip_address(ip_str)
        return (ip.is_private or ip.is_loopback or ip.is_reserved
                or ip.is_link_local or ip.is_multicast)


class RandomUserAgentMiddleware:
    """UA 轮换：每个请求从浏览器 UA 池随机挑一个。

    取舍说明：robots 协议的精神是"亮明爬虫身份"，但主流站点普遍
    按浏览器 UA 校验请求，固定标识会被直接拒绝。折中做法是：
    UA 用浏览器池轮换（降低单一指纹特征），同时遵守 robots、
    限速让步、只采公开页面 —— "身份可以普通，行为必须礼貌"。
    """

    # ClassVar 声明"类级常量"：ruff 认可、也表明不会被实例改写
    USER_AGENT_POOL: ClassVar[list] = [
        ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
         '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'),
        ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
         '(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'),
        ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
         '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0'),
    ]

    def process_request(self, request):
        """随机挑一个浏览器 UA 覆盖默认值（轮换指纹；新签名无 spider 参数）。"""
        request.headers['User-Agent'] = random.choice(self.USER_AGENT_POOL)
