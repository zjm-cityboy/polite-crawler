# 爬虫应用镜像：同时承载 scrapyd（守护进程）与 scrapydweb（监控面板）
# 两倍只装一次依赖，起两个容器各跑各的命令（见 docker-compose.yml）

FROM python:3.11-slim

# 不装编译链的纯 Python 依赖环境直接装；WORKDIR 固定工作目录
WORKDIR /app

# 先单独拷贝 requirements：依赖层没变时 Docker 构建缓存直接复用（提速关键）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 再拷贝全部代码（scrapy.cfg 必须在，scrapyd-deploy 与运行时都要读它）
COPY . .

# 6800=scrapyd 的 HTTP API 端口；5000=scrapydweb 面板端口
EXPOSE 6800 5000

# 默认启动守护进程；scrapydweb 服务在 compose 里覆盖此命令
CMD ["scrapyd"]
