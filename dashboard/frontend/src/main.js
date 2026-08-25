// 应用入口：创建 Vue 实例 + 注册 Element Plus 组件库
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import { createApp } from 'vue'
import App from './App.vue'

createApp(App).use(ElementPlus).mount('#app')
