<script setup>
// 每日采集量柱状图：ECharts 挂在模板 ref 上（不是 DOM id），props 数据驱动重绘
import * as echarts from 'echarts'
import { onMounted, ref, watch } from 'vue'

const props = defineProps({
  trend: { type: Array, default: () => [] }, // [{date, count}, ...]
})

const el = ref(null) // 模板引用：指向 <div> 真实 DOM
let chart = null

function render() {
  chart.setOption({
    grid: { left: 40, right: 16, top: 24, bottom: 28 },
    tooltip: { trigger: 'axis' },
    xAxis: {
      type: 'category',
      data: props.trend.map((t) => t.date),
      axisLabel: { color: '#8492a6' },
    },
    yAxis: { type: 'value', axisLabel: { color: '#8492a6' }, splitLine: { lineStyle: { color: '#eef2f7' } } },
    series: [
      {
        type: 'bar',
        data: props.trend.map((t) => t.count),
        barMaxWidth: 36,
        itemStyle: { color: '#409eff', borderRadius: [4, 4, 0, 0] },
      },
    ],
  })
}

// 挂载后初始化图表实例；trend 数据到达/变化时重绘（watch 深比较数组引用）
onMounted(() => {
  chart = echarts.init(el.value)
  render()
})
watch(() => props.trend, render)
</script>

<template>
  <div ref="el" class="chart" />
</template>

<style scoped>
.chart {
  width: 100%;
  height: 280px;
}
</style>
