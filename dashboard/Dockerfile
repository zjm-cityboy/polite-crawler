# 数据看板镜像：多阶段构建（前端编译期 + 运行期分离）
#
# 阶段一 web：node 环境编译 Vue 前端 → 产出纯静态文件 dist/
# 阶段二运行：python 环境只装 FastAPI 三件套，带上 dist 即可
# 好处：最终镜像不含 node_modules 和 node 本身（体积从 ~1GB 降到 ~200MB）

FROM node:20-alpine AS web
WORKDIR /web
# 先拷 package.json 装依赖：dashboard 代码没变时 Docker 缓存直接复用依赖层
COPY frontend/package*.json ./
RUN npm install --silent
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn psycopg2-binary
COPY main.py .
# 前端构建产物放进 main.py 托管的 static/ 目录（前后端同源，无需跨域）
COPY --from=web /web/dist ./static

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
