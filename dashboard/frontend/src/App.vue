<script setup>
// 应用壳（组合层）：提交爬取 → 任务状态 → 统计看板 的完整使用闭环
// 数据逻辑全部在 useDashboard composable，本组件只负责编排各展示组件
import { onMounted, onUnmounted } from 'vue'
import ArticleTable from './components/ArticleTable.vue'
import CrawlForm from './components/CrawlForm.vue'
import JobsPanel from './components/JobsPanel.vue'
import SourceChart from './components/SourceChart.vue'
import StatsCards from './components/StatsCards.vue'
import TrendChart from './components/TrendChart.vue'
import { useDashboard } from './composables/useDashboard'

const {
  stats, articles, total, page, size, loading, jobs,
  refreshAll, startJobsPolling, stopJobsPolling, changePage,
} = useDashboard()

onMounted(() => {
  refreshAll()          // 首屏：任务 + 统计 + 文章一次拉齐
  startJobsPolling()    // 之后 15 秒一轮：任务跑完数据自动更新
})
onUnmounted(stopJobsPolling)

// 表单提交成功后的回调：立即刷一轮任务列表（不用等 15 秒轮询）
function onSubmitted() {
  refreshAll()
}
</script>

<template>
  <div class="page">
    <header class="hero">
      <div>
        <h1>News Crawler 采集控制台</h1>
        <p class="sub">提交入口链接 → 爬虫自动发现并采集 → 数据实时上图</p>
      </div>
      <el-tag effect="plain" round>polite-crawler</el-tag>
    </header>

    <CrawlForm class="block" @submitted="onSubmitted" />

    <el-row :gutter="16" class="block">
      <el-col :span="9">
        <JobsPanel :jobs="jobs" />
      </el-col>
      <el-col :span="15">
        <StatsCards :stats="stats" />
      </el-col>
    </el-row>

    <el-row :gutter="16" class="block">
      <el-col :span="14">
        <el-card shadow="never">
          <template #header>每日采集量</template>
          <TrendChart :trend="stats.trend" />
        </el-card>
      </el-col>
      <el-col :span="10">
        <el-card shadow="never">
          <template #header>来源域名分布</template>
          <SourceChart :domains="stats.domains" />
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never" class="block">
      <template #header>文章列表（点击标题查看原文）</template>
      <ArticleTable
        :items="articles"
        :total="total"
        :page="page"
        :size="size"
        :loading="loading"
        @page-change="changePage"
      />
    </el-card>
  </div>
</template>

<style scoped>
.page {
  max-width: 1200px;
  margin: 0 auto;
  padding: 24px 20px 48px;
  background: #f5f7fa;
  min-height: 100vh;
}
.hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 4px 20px;
}
.hero h1 {
  font-size: 22px;
  color: #1f2d3d;
  margin: 0 0 6px;
}
.sub {
  color: #8492a6;
  font-size: 13px;
  margin: 0;
}
.block {
  margin-bottom: 16px;
}
</style>
