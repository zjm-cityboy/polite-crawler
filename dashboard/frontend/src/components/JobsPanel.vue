<script setup>
// 任务面板：纯展示组件（任务数据由父组件轮询后传入，状态点动画自己管）
defineProps({
  jobs: { type: Object, required: true }, // {pending, running, finished}
})

// 状态点颜色：排队灰、运行绿（闪烁）、完成蓝
const dot = (kind) =>
  kind === 'running' ? '#67c23a' : kind === 'pending' ? '#909399' : '#409eff'
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div class="head">
        <span>爬取任务</span>
      </div>
    </template>

    <div v-if="jobs.running.length" class="group">
      <div v-for="j in jobs.running" :key="j.id" class="job running">
        <span class="d" :style="{ background: dot('running') }" />
        <span class="id">{{ j.id }}</span>
        <span class="time">{{ j.start_time }}</span>
        <el-tag size="small" type="success" effect="plain">运行中</el-tag>
      </div>
    </div>
    <div v-if="jobs.pending.length" class="group">
      <div v-for="j in jobs.pending" :key="j.id" class="job">
        <span class="d" :style="{ background: dot('pending') }" />
        <span class="id">{{ j.id }}</span>
        <el-tag size="small" type="info" effect="plain">排队中</el-tag>
      </div>
    </div>

    <div class="group-title" v-if="jobs.finished.length">最近完成</div>
    <div v-for="j in jobs.finished" :key="j.id" class="job">
      <span class="d" :style="{ background: dot('finished') }" />
      <span class="id">{{ j.id }}</span>
      <span class="time">{{ j.start_time }} → {{ j.end_time }}</span>
    </div>

    <el-empty
      v-if="!jobs.running.length && !jobs.pending.length && !jobs.finished.length"
      description="还没有任务：在上方提交一个入口页试试"
      :image-size="60"
    />
  </el-card>
</template>

<style scoped>
.head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.job {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 0;
  font-size: 13px;
  color: #2c3e50;
}
.d {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.running .d {
  animation: blink 1.2s infinite;
}
@keyframes blink {
  50% {
    opacity: 0.3;
  }
}
.id {
  font-family: monospace;
}
.time {
  color: #8492a6;
  font-size: 12px;
}
.group-title {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed #e4e9f0;
  font-size: 12px;
  color: #8492a6;
}
</style>
