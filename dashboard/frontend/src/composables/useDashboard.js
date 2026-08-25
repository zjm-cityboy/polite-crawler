// 数据获取 composable：统计 + 文章分页 + 爬取任务提交/轮询
import { ref } from 'vue'

export function useDashboard() {
  const stats = ref({ total: 0, today: 0, domains: [], trend: [] })
  const articles = ref([])
  const total = ref(0)
  const page = ref(1)
  const size = ref(15)
  const loading = ref(false)
  const jobs = ref({ pending: [], running: [], finished: [] })
  let jobsTimer = null

  // 拉统计汇总（卡片 + 两张图共用一份数据）
  async function fetchStats() {
    const res = await fetch('/api/stats')
    stats.value = await res.json()
  }

  // 拉文章列表（page/size 变化时调用）
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

  // 拉任务列表 + 顺带刷新统计（任务跑完数据会变，一起刷省一次手动）
  async function fetchJobs() {
    const res = await fetch('/api/jobs')
    jobs.value = await res.json()
  }

  // 任务/数据统一刷新：提交爬取后立即调，轮询到点也调
  async function refreshAll() {
    await Promise.all([fetchJobs(), fetchStats(), fetchArticles()])
  }

  // 任务轮询：15 秒一次（组件卸载时 clearInterval 防泄漏）
  function startJobsPolling() {
    jobsTimer = setInterval(refreshAll, 15000)
  }
  function stopJobsPolling() {
    clearInterval(jobsTimer)
  }

  // 表格翻页：更新页码后重新拉取
  function changePage(p) {
    page.value = p
    fetchArticles()
  }

  return {
    stats, articles, total, page, size, loading, jobs,
    fetchStats, fetchArticles, fetchJobs, refreshAll,
    startJobsPolling, stopJobsPolling, changePage,
  }
}
