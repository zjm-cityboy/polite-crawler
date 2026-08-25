<script setup>
// 提交爬取表单：输入入口 URL → POST /api/crawl 触发爬虫任务
import { ref } from 'vue'
import { ElMessage } from 'element-plus'

const emit = defineEmits(['submitted'])   // 提交成功后通知父组件刷新任务列表

const url = ref('')
const submitting = ref(false)

async function submit() {
  const value = url.value.trim()
  if (!value) {
    ElMessage.warning('请先粘贴入口页链接（如新闻频道首页）')
    return
  }
  submitting.value = true
  try {
    const res = await fetch('/api/crawl', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: value }),
    })
    const data = await res.json()
    if (!res.ok) {
      // 后端 400：协议/白名单校验不过，detail 里是原因
      ElMessage.error(data.detail || '提交失败')
      return
    }
    ElMessage.success(`任务已提交（${data.jobid.slice(0, 8)}），爬虫开始工作`)
    url.value = ''
    emit('submitted')
  } catch (e) {
    ElMessage.error('网络异常，稍后再试')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <el-card shadow="never" class="crawl-form">
    <div class="row">
      <el-input
        v-model="url"
        placeholder="粘贴入口页链接（频道首页或任意文章页），如 http://news.weather.com.cn/index.shtml"
        size="large"
        clearable
        @keyup.enter="submit"
      />
      <el-button
        type="primary"
        size="large"
        :loading="submitting"
        class="btn"
        @click="submit"
      >
        开始爬取
      </el-button>
    </div>
    <div class="hint">
      爬虫会自动发现页面里的文章链接并采集（限白名单站点，采满自动停）；
      结果稍后出现在下方看板
    </div>
  </el-card>
</template>

<style scoped>
.row {
  display: flex;
  gap: 12px;
}
.btn {
  flex-shrink: 0;
}
.hint {
  margin-top: 8px;
  font-size: 12px;
  color: #8492a6;
}
</style>
