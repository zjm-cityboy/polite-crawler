// 数据获取 composable：统计汇总 + 文章分页，统一管理 loading 态
import { ref } from 'vue'

export function useDashboard() {
  const stats = ref({ total: 0, today: 0, domains: [], trend: [] })
  const articles = ref([])
  const total = ref(0)
  const page = ref(1)
  const size = ref(15)
  const loading = ref(false)

  // 拉统计汇总（卡片 + 两张图共用一份数据）
  async function fetchStats() {
    const res = await fetch('/api/stats')
    stats.value = await res.json()
  }

  // 拉文章列表（page/size 变化时调用；接口参数即查询串拼接）
  async function fetchArticles() {
    loading.value = true
    try {
      const res = await fetch(
        `/api/articles?page=${page.value}&size=${size.value}`,
      )
      const data = await res.json()
      articles.value = data.items
      total.value = data.total
    } finally {
      loading.value = false
    }
  }

  // 表格翻页：更新页码后重新拉取
  function changePage(p) {
    page.value = p
    fetchArticles()
  }

  return { stats, articles, total, page, size, loading, fetchStats, fetchArticles, changePage }
}
