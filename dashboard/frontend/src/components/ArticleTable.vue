<script setup>
// 文章列表：分页表格（数据由父组件传入，翻页事件向父组件冒泡）
defineProps({
  items: { type: Array, default: () => [] },
  total: { type: Number, default: 0 },
  page: { type: Number, default: 1 },
  size: { type: Number, default: 15 },
  loading: { type: Boolean, default: false },
})

// 翻页不自己拉数据：emit 给父组件（useDashboard.changePage）统一处理
const emit = defineEmits(['page-change'])
</script>

<template>
  <el-table :data="items" v-loading="loading" stripe>
    <el-table-column prop="id" label="ID" width="70" />
    <el-table-column label="标题" min-width="320">
      <!-- 标题可点击跳原文（target=_blank 新开标签页） -->
      <template #default="{ row }">
        <a :href="row.url" target="_blank" rel="noopener" class="title-link">
          {{ row.title }}
        </a>
      </template>
    </el-table-column>
    <el-table-column prop="published" label="发布日期" width="110" />
    <el-table-column prop="content_len" label="正文字数" width="100" />
    <el-table-column prop="crawled_at" label="采集时间" width="150" />
    <template #empty>
      <el-empty description="暂无数据：先往 seeds.txt 加种子跑一次采集" />
    </template>
  </el-table>

  <div class="pager">
    <el-pagination
      background
      layout="total, prev, pager, next"
      :total="total"
      :current-page="page"
      :page-size="size"
      @current-change="emit('page-change', $event)"
    />
  </div>
</template>

<style scoped>
.title-link {
  color: #2c3e50;
  text-decoration: none;
}
.title-link:hover {
  color: #409eff;
}
.pager {
  margin-top: 14px;
  display: flex;
  justify-content: flex-end;
}
</style>
