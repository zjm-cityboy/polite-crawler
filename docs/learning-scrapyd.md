# Scrapyd 与 ScrapydWeb 学习文档（对照本项目实战）

> 定位：看完这份文档，你能讲清楚"爬虫怎么从脚本变成可远程管理的服务"。

## 一、它们是什么（一句话 + 比喻）

- **Scrapyd** = 爬虫的" daemon 守护进程"：一个常驻后台的爬虫管家。
- **ScrapydWeb** = 这个管家的"遥控器"：一个网页面板，点按钮代替敲 API。

比喻：没有 Scrapyd 时，爬虫像台**老式洗衣机**——你得守在跟前按开关（SSH 上服务器、敲命令、盯着终端）；有了 Scrapyd + ScrapydWeb，变成**智能家电**——你在手机上（浏览器里）就能启动、暂停、看运行记录，还能设定时任务。

## 二、为什么需要它（没有会怎样）

| 痛点（裸跑 scrapy） | Scrapyd 的解法 |
|---|---|
| 每次跑爬虫要 SSH 上服务器敲命令 | HTTP API 远程触发：`curl schedule.json` |
| 爬虫代码更新要手动拷文件到服务器 | `scrapyd-deploy` 一条命令打包上传（版本化管理） |
| 跑完的日志散落各处 | 集中存在服务端 `/logs/项目/爬虫/任务ID.log` |
| 定时任务要自己写 crontab | API/面板直接加定时任务（timer） |
| 多台机器各跑各的，没有统一视图 | ScrapydWeb 多节点管理（这正是 NewsCrawl 集群调度的基础） |

**一句话总结定位：Scrapy 负责"怎么爬"，Scrapyd 负责"在哪爬、何时爬、怎么管"。**

## 三、核心概念（最小必要知识）

### 1. 项目 → 爬虫 → 任务（job）三层结构
```
news_crawler（项目）          ← 一个 Scrapy 工程打成一个包
  └── article（爬虫）         ← 工程里的 Spider 类（name 属性）
        └── job（任务）        ← 每触发一次运行 = 一个 job，有唯一 jobid
```

### 2. 六个最常用的 HTTP API（全部本项目实测可用）

| 接口 | 作用 | 本项目实例 |
|---|---|---|
| `/daemonstatus.json` | 守护进程心跳 | `curl localhost:6800/daemonstatus.json` |
| `/addversion.json` | 上传新版本（部署） | scrapyd-deploy 内部调的就是它 |
| `/schedule.json` | 触发一次爬取 | `curl -d project=news_crawler -d spider=article` |
| `/listjobs.json` | 查任务（pending/running/finished） | `curl "localhost:6800/listjobs.json?project=news_crawler"` |
| `/cancel.json` | 取消运行中任务 | - |
| `/listspiders.json` | 列出项目里的爬虫 | - |

### 3. 部署流程（本项目实际跑通的命令）

```bash
# ① scrapy.cfg 里声明部署目标（[deploy:news_scrapyd] url + project）
# ② 一条命令打包上传
scrapyd-deploy news_scrapyd
# 返回 {"spiders": 1, "status": "ok"} = 部署成功

# ③ 远程触发
curl http://localhost:6800/schedule.json -d project=news_crawler -d spider=article
# 返回 {"jobid": "5333fa9a...", "status": "ok"}

# ④ 看结果
curl "http://localhost:6800/listjobs.json?project=news_crawler"
# 任务出现在 finished 列表，日志在 /logs/news_crawler/article/<jobid>.log
```

## 四、在本项目中的位置（docker-compose 五容器）

```
crawler-scrapyd     ← 爬虫应用容器：装 scrapy+scrapyd，暴露 6800
crawler-scrapydweb  ← 监控面板容器：只装 scrapydweb，暴露 5000
                     （两个容器必须分开装！原因见踩坑 #1）
```

ScrapydWeb 通过 HTTP 连 `scrapyd:6800`（compose 服务名互访），浏览器打开
`http://localhost:5000` 就能看到任务列表、日志、定时任务页面。

## 五、踩坑实录（全部本项目真实发生，一天踩完）

1. **ScrapydWeb 与 Scrapy 不能装同一环境**：scrapydweb 1.6.0 钉死
   `w3lib==2.0.0` 等一串老依赖，与 Scrapy 2.18 依赖链正面冲突
   （`ResolutionImpossible`）。解法：**独立镜像**（Dockerfile.web 只装 scrapydweb）。
   本质认识：面板只是通过 HTTP API 连 scrapyd，根本不需要爬虫代码。
2. **老教程的 scrapyd.conf 带 [services] 段**：引用的 `scrapyd.webutils`
   模块在 scrapyd 1.6 已移除，照抄直接启动崩溃（`ModuleNotFoundError`）。
   新版服务默认注册，**不能**手动声明。
3. **配置文件命名**：ScrapydWeb 1.6.0 认 `scrapydweb_settings_v11.py`
   （NewsCrawl 用的 v10 是老版命名），找不到 v11 会复制默认配置后退出。
4. **SCRAPYD_SERVERS 格式**：字符串 `'scrapyd:6800'` 最稳；五元组顺序是
   `(用户名, 密码, host, 端口字符串, 分组)` —— 端口传 int 直接
   `AttributeError: 'int' object has no attribute 'strip'`。
5. **BuildKit + 中文路径**：在中文目录 `docker compose build` 报
   `x-docker-expose-session-sharedkey contains non-printable ASCII`。
   解法：`DOCKER_BUILDKIT=0` 走经典构建器。

## 六、面试怎么答

**Q：Scrapyd 和直接跑 scrapy crawl 有什么区别？**
要点：scrapy crawl 是一次性进程（跑完退出、日志在本地）；Scrapyd 是常驻服务，提供 HTTP API 的远程部署/触发/取消/日志收集/定时任务，是爬虫从"脚本"到"服务"的关键一步——多机部署时配合 ScrapydWeb 做统一管理（NewsCrawl 的集群调度就是这么做的：管理脚本调 ScrapydWeb 的 API 批量下发任务到多节点）。

**Q：部署过吗？具体流程？**
按上面"部署流程"四步答，加上踩坑 #1（依赖冲突分开装）——说出这个坑基本能证明真动手做过。

## 七、延伸（下一步可以学）

- ScrapydWeb 的定时任务（Timer Tasks）：面板上直接配置周期性 schedule
- NewsCrawl 的集群分配策略：按爬虫首字母/数量分组下发到多节点
- logparser：解析 scrapyd 日志成结构化数据（ScrapydWeb 的日志统计页依赖它）
