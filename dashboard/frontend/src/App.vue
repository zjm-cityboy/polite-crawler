<script setup>
// 应用壳（组合层）：头部 + 统计卡片 + 双图表 + 文章表格
// 数据逻辑全部在 useDashboard composable，本组件只负责编排各展示组件
import { onMounted } from 'vue'
import ArticleTable from './components/ArticleTable.vue'
import SourceChart from './components/SourceChart.vue'
import StatsCards from './components/StatsCards.vue'
import TrendChart from './components/TrendChart.vue'
import { useDashboard } from './composables/useDashboard'

const { stats, articles, total, page, size, loading, fetchStats, fetchArticles, changePage } =
  useDashboard()

onMounted(() => {
  fetchStats()
  fetchArticles()
})
</script>

<template>
  <div class="page">
    <header class="hero">
      <div>
        <h1>News Crawler 采集看板</h1>
        <p class="sub">Scrapy × Redis 去重 × PostgreSQL × Kafka —— 采集成果实时视图</p>
      </div>
      <el-tag effect="plain" round>polite-crawler</el-tag>
    </header>

    <StatsCards :stats="stats" class="block" />

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
