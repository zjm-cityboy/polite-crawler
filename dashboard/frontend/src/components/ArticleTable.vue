<script setup>
// 文章列表：分页表格 + "查看正文"弹窗（按需加载单篇全文）
import { ref } from 'vue'
import { ElMessage } from 'element-plus'

defineProps({
  items: { type: Array, default: () => [] },
  total: { type: Number, default: 0 },
  page: { type: Number, default: 1 },
  size: { type: Number, default: 15 },
  loading: { type: Boolean, default: false },
})

// 翻页不自己拉数据：emit 给父组件（useDashboard.changePage）统一处理
const emit = defineEmits(['page-change'])

// ---- 正文弹窗状态（本组件自治：点开才加载，关掉即清） ----
const dialog = ref(false)       // 弹窗开关
const detail = ref(null)        // 当前展示的文章详情
const detailLoading = ref(false)

async function showDetail(row) {
  detailLoading.value = true
  dialog.value = true
  try {
    const res = await fetch(`/api/article/${row.id}`)
    if (!res.ok) {
      ElMessage.error('加载正文失败')
      dialog.value = false
      return
    }
    detail.value = await res.json()
  } finally {
    detailLoading.value = false
  }
}
</script>

<template>
  <el-table :data="items" v-loading="loading" stripe>
    <el-table-column prop="id" label="ID" width="70" />
    <el-table-column label="标题" min-width="280">
      <!-- 标题可点击跳原文（新开标签页） -->
      <template #default="{ row }">
        <a :href="row.url" target="_blank" rel="noopener" class="title-link">
          {{ row.title }}
        </a>
      </template>
    </el-table-column>
    <el-table-column prop="published" label="发布日期" width="110" />
    <el-table-column prop="content_len" label="字数" width="90" />
    <el-table-column prop="crawled_at" label="采集时间" width="150" />
    <el-table-column label="操作" width="110" fixed="right">
      <template #default="{ row }">
        <el-button link type="primary" @click="showDetail(row)">
          查看正文
        </el-button>
      </template>
    </el-table-column>
    <template #empty>
      <el-empty description="暂无数据：在上方提交一个入口页试试" />
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

  <!-- 正文弹窗：展示爬到的 Markdown 原文（pre-wrap 保留换行结构） -->
  <el-dialog v-model="dialog" :title="detail?.title || '加载中…'" width="720px" top="6vh">
    <div v-loading="detailLoading" class="detail">
      <div v-if="detail" class="meta">
        <el-tag size="small" effect="plain">{{ detail.published }}</el-tag>
        <span class="meta-item">{{ detail.content_md.length }} 字</span>
        <a :href="detail.url" target="_blank" rel="noopener" class="meta-link">原网页 ↗</a>
      </div>
      <pre v-if="detail" class="content">{{ detail.content_md }}</pre>
    </div>
  </el-dialog>
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
.meta {
  display: flex;
  align-items: center;
  gap: 12px;
  padding-bottom: 10px;
  border-bottom: 1px solid #eef2f7;
}
.meta-item {
  color: #8492a6;
  font-size: 12px;
}
.meta-link {
  color: #409eff;
  font-size: 12px;
  text-decoration: none;
}
.content {
  white-space: pre-wrap;      /* 保留 Markdown 的换行与空行结构 */
  word-break: break-word;
  font-family: inherit;       /* 不用等宽字体，正文更像文章 */
  font-size: 14px;
  line-height: 1.8;
  color: #2c3e50;
  max-height: 60vh;
  overflow-y: auto;
  margin: 12px 0 0;
}
</style>
