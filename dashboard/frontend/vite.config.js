// Vite 配置：开发模式把 /api 请求转发给本地 FastAPI（8080 容器映射端口）
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      // 开发时前端跑 5173、后端跑 8080（compose 的 dashboard 服务）
      '/api': { target: 'http://localhost:8080', changeOrigin: true },
    },
  },
})
