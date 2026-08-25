# News Crawler —— 企业级礼貌爬虫系统

基于 **Scrapy** 的新闻/文章采集系统：**Redis 双重去重 → PostgreSQL 入库 → Kafka 下游分发 → Scrapyd/ScrapydWeb 部署监控 + 数据看板**，六容器 Docker Compose 一键启动。定位为 RAG 系统的知识库语料采集端（默认采集中国天气网，与气象 RAG 项目同源）。

> "礼貌爬虫"（polite crawler）= 遵守 robots.txt、限速让步、聚焦白名单站点、只采公开页面 —— 合规是本系统的第一设计约束，详见下文「合规设计」。

## 架构

```
                    ┌──────────────────────────────────────────────┐
                    │                Docker Compose                │
                    │                                              │
  seeds.txt         │  ┌─────────┐   ┌─────────┐   ┌──────────┐   │
  （种子清单）──────┼─▶│ Scrapyd │──▶│  Redis  │   │  Kafka   │   │
                    │  │  :6800  │   │  :6379  │   │  :9092   │   │
                    │  └────┬────┘   └────▲────┘   └────▲─────┘   │
                    │       │ 请求指纹去重│ 内容指纹  消息 │         │
                    │       │            │              │         │
                    │       ▼            │              │         │
                    │  ┌──────────┐      │              │         │
                    │  │ Scrapy   │──────┘──────────────┘         │
                    │  │ pipeline │  RedisDedupe→PG→KafkaPipeline │
                    │  └────┬─────┘                               │
                    │       ▼                                     │
                    │  ┌──────────────┐     ┌──────────────────┐  │
                    │  │ PostgreSQL   │     │   ScrapydWeb     │  │
                    │  │   :5433      │     │ 面板 :5000       │  │
                    │  └──────────────┘     └──────────────────┘  │
                    └──────────────────────────────────────────────┘
                              │                    │
              下游消费（kafka_consumer.py）   浏览器监控任务/日志/定时
```

数据流一句话：种子 URL 经合规中间件校验 → Scrapy 下载（AutoThrottle 限速 + UA 轮换）→ trafilatura 提取正文 → 内容指纹去重（Redis）→ 入库（PostgreSQL，参数绑定 + UNIQUE 兜底）→ 推送元数据（Kafka）→ 任意下游订阅消费。

## 技术选型（对标生产项目 [NewsCrawl](https://github.com/casual-silva/NewsCrawl)）

| 能力 | NewsCrawl | 本项目 | 说明 |
|---|---|---|---|
| 采集框架 | Scrapy | Scrapy 2.18 | 同 |
| 正文抽取 | GNE | trafilatura 2.2 | 均为通用新闻正文抽取，中文支持好 |
| 去重 | Redis | Redis 7（手写 DupeFilter） | 请求指纹 + 内容指纹双重去重 |
| 业务存储 | MySQL | PostgreSQL 18 | 数据库级 UNIQUE 约束兜底去重 |
| 下游分发 | Kafka | Kafka 3.7（KRaft） | 生产者/消费者解耦 |
| 部署监控 | Scrapyd + ScrapydWeb | 同（分容器隔离依赖） | ScrapydWeb 与 Scrapy 依赖冲突，独立镜像 |
| 编排 | Docker Compose | Docker Compose（5 服务） | 同 |

## 快速开始

### 1. 启动全套基础设施（PostgreSQL / Redis / Kafka / Scrapyd / ScrapydWeb）

```bash
docker compose up -d
# 首次构建镜像（中文路径需走经典构建器）：
DOCKER_BUILDKIT=0 COMPOSE_DOCKER_CLI_BUILD=0 docker compose up -d --build
```

就绪后：
- Scrapyd API：http://localhost:6800/daemonstatus.json
- ScrapydWeb 面板：http://localhost:5000
- PG：`localhost:5433`（库 `crawler`，用户/密码 `postgres/postgres`，学习环境默认值）

### 2. 本机直跑（开发调试）

```bash
pip install -r requirements.txt
# 种子：编辑 seeds.txt（每行一个 URL；目标域名需在 settings.py 白名单内）
python -m scrapy crawl article
# 离线单元测试（不联网、不依赖外部服务）
python -m pytest tests/ -v
```

### 3. 部署到 Scrapyd（服务化运行）

```bash
scrapyd-deploy news_scrapyd                        # 打包上传
curl http://localhost:6800/schedule.json \
     -d project=news_crawler -d spider=article     # API 触发
curl "http://localhost:6800/listjobs.json?project=news_crawler"  # 查任务
```

### 4. 下游消费（Kafka）

```bash
python kafka_consumer.py    # 订阅 articles 主题，打印收到的文章元数据
```

### 5. 数据看板（浏览器打开）

```
http://localhost:8080
```

Vue3 + Element Plus + ECharts 看板：统计卡片（累计/今日/来源域名/峰值日采集）、每日采集量柱状图、来源域名分布环形图、文章分页列表（点击标题跳原文）。后端 FastAPI（`dashboard/main.py`）读 PG 提供 `/api/stats`、`/api/articles` 接口并托管前端静态页——**多阶段构建**：node 编译前端 → python 运行镜像（最终镜像不含 node_modules）。

### 6. 验证数据

```bash
docker exec crawler-db psql -U postgres -d crawler \
  -c "SELECT id, LEFT(title,20), LENGTH(content_md) FROM articles;"
docker exec crawler-redis redis-cli SCARD dupefilter:urls
docker exec crawler-redis redis-cli SCARD dupefilter:content
```

## 合规设计（法律调研落地）

依据《网络安全法》《数据安全法》《个人信息保护法》及相关司法判例（[调研来源](docs/legal-notes.md)），爬虫的刑事风险集中在**突破/绕开反爬措施**，民事风险集中在**违反 robots 协议的大规模采集**。本系统的技术落地：

| 约束 | 实现 |
|---|---|
| 遵守 robots.txt | `ROBOTSTXT_OBEY = True`（框架级强制） |
| 爬取边界可控 | 真爬虫模式做**受控链接发现**，四重刹车：①站点白名单（中间件强制）②URL 模式正则（只跟文章形状链接）③深度限制（`DEPTH_LIMIT=2`）④数量熔断（采满 30 篇自动停 + 总请求数上限） |
| 不给目标服务器造成压力 | AutoThrottle 自动限速 + 每域名并发 1 + 随机化下载间隔 |
| 防 SSRF | 下载中间件解析目标 IP，拒绝私网/环回/保留地址 |
| SQL 注入防护 | 全部参数绑定，无字符串拼接 SQL |
| 仅公开数据 | 不模拟登录、不绕验证码、不采个人信息字段 |

## 双重去重

```
请求级  dupefilter:urls    （Redis SET + SADD）→ 挡"爬过的链接"
内容级  dupefilter:content （正文 SHA1 + SADD）→ 挡"换链接的重复文章"
兜底    articles.content_fp UNIQUE             → Redis 指纹全丢也不重复入库
```

已验证的跨进程语义：本机跑过的 URL，容器内触发的任务会自动跳过（共享同一 Redis 账本）—— 分布式去重的最小现场。

## 项目结构

```
├── scrapy.cfg                  # 部署配置（scrapyd-deploy 目标）
├── news_crawler/               # Scrapy 工程
│   ├── settings.py             #   全局配置（合规/限速/管道/服务地址）
│   ├── items.py                #   ArticleItem 数据结构
│   ├── spiders/article_spider.py   # 入口页链接发现（受控）+ trafilatura 正文提取
│   ├── dupefilter.py           #   Redis 请求级去重（手写 scrapy-redis 核心）
│   ├── middlewares.py          #   合规中间件（白名单/SSRF）+ UA 轮换
│   ├── pipelines.py            #   RedisDedupe → PostgreSQL → Kafka 管道链
│   └── db.py                   #   PG 连接池（双检锁 + 上下文管理器）
├── dashboard/                  # 采集数据看板（FastAPI + Vue3，多阶段构建）
│   ├── main.py                 #   统计/分页接口 + 静态托管
│   ├── Dockerfile              #   node 编译 → python 运行两阶段
│   └── frontend/               #   Vue3 + Element Plus + ECharts 前端
├── weibo_spider.py             # 微博评论采集（独立脚本：课程作业专项）
├── kafka_consumer.py           # Kafka 下游消费者示例
├── tests/                      # 离线单元测试（11 例）
├── docs/                       # 学习文档（Redis / Scrapyd / Kafka / 法律调研）
├── docker-compose.yml          # 六服务编排
├── Dockerfile / Dockerfile.web # 应用镜像（scrapyd / scrapydweb 分离）
└── scrapyd.conf / scrapydweb_settings_v11.py
```

## 学习文档

- [docs/learning-redis.md](docs/learning-redis.md) —— Redis：为什么去重用它、SADD 原子性、与 PG 分工
- [docs/learning-scrapyd.md](docs/learning-scrapyd.md) —— Scrapyd/ScrapydWeb：部署/触发/监控全流程
- [docs/learning-kafka.md](docs/learning-kafka.md) —— Kafka：生产者消费者解耦、offset、容器化双监听器

## 踩坑记录（全部实测复现）

1. PG 18 镜像要求数据卷挂 `/var/lib/postgresql`（挂 `.../data` 直接拒绝启动）
2. Scrapy 2.18 移除 `start_requests()`，必须用 `async def start()`（旧方法被静默忽略）
3. Scrapy 2.13+ 中间件/管道钩子新签名无 `spider` 参数（旧签名触发 reactor 故障）
4. scrapyd 1.6 移除 `scrapyd.webutils`，老教程的 `[services]` 配置段导致启动即崩
5. ScrapydWeb 与 Scrapy 依赖冲突（钉死 w3lib==2.0.0），必须分镜像安装
6. ScrapydWeb 1.6.0 配置文件为 `*_v11.py`，`SCRAPYD_SERVERS` 用字符串格式最稳
7. kafka-python 不指定 `api_version` 时对 Kafka 3.7 协商失败（消费者静默收不到消息）
8. Docker BuildKit 不支持中文构建路径（`DOCKER_BUILDKIT=0` 走经典构建器）
9. `@contextmanager` 装饰器遗漏导致 `with` 生成器报 `AttributeError: __enter__`

## License

AGPL-3.0，见 [LICENSE](LICENSE)。
