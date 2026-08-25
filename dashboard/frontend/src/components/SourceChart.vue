<script setup>
// 来源域名分布饼图：环形图展示各站点采集占比
import * as echarts from 'echarts'
import { onMounted, ref, watch } from 'vue'

const props = defineProps({
  domains: { type: Array, default: () => [] }, // [{name, value}, ...]
})

const el = ref(null)
let chart = null

function render() {
  chart.setOption({
    tooltip: { trigger: 'item', formatter: '{b}: {c} 篇（{d}%）' },
    legend: { bottom: 0, textStyle: { color: '#8492a6', fontSize: 12 } },
    series: [
      {
        type: 'pie',
        radius: ['42%', '68%'], // 环形：内半径/外半径
        center: ['50%', '44%'],
        label: { show: false },
        data: props.domains,
        itemStyle: { borderColor: '#fff', borderWidth: 2, borderRadius: 4 },
      },
    ],
  })
}

onMounted(() => {
  chart = echarts.init(el.value)
  render()
})
watch(() => props.domains, render)
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
