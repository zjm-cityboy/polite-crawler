<script setup>
// 统计卡片：纯展示组件（数据从父组件 props 流入，无自身状态）
import { computed } from 'vue'

const props = defineProps({
  stats: { type: Object, required: true },
})

// 卡片配置用 computed 派生：stats 一变自动重算，模板保持 declarative
const cards = computed(() => [
  { label: '累计文章', value: props.stats.total, unit: '篇' },
  { label: '今日新增', value: props.stats.today, unit: '篇' },
  { label: '来源域名', value: props.stats.domains.length, unit: '个' },
  {
    label: '峰值日采集',
    value: Math.max(0, ...props.stats.trend.map((t) => t.count)),
    unit: '篇',
  },
])
</script>

<template>
  <el-row :gutter="16">
    <el-col v-for="c in cards" :key="c.label" :span="6">
      <div class="stat-card">
        <div class="stat-value">
          {{ c.value }}<span class="stat-unit">{{ c.unit }}</span>
        </div>
        <div class="stat-label">{{ c.label }}</div>
      </div>
    </el-col>
  </el-row>
</template>

<style scoped>
.stat-card {
  background: linear-gradient(135deg, #f8fafc 0%, #eef2f7 100%);
  border: 1px solid #e4e9f0;
  border-radius: 10px;
  padding: 18px 22px;
}
.stat-value {
  font-size: 30px;
  font-weight: 700;
  color: #1f2d3d;
}
.stat-unit {
  font-size: 13px;
  color: #8492a6;
  margin-left: 4px;
}
.stat-label {
  margin-top: 6px;
  font-size: 13px;
  color: #8492a6;
}
</style>
