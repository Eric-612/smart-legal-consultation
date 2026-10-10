<!--
  ============================================================
  DisclaimerBanner.vue —— 全局免责声明横幅
  从 ChatView.vue 抽出的独立组件（与讲义 day05 §3.2 目录结构一致）。
  法律合规底线：任何页面只要涉及咨询/建议，就必须展示本横幅。
  ============================================================
-->
<script setup>
defineProps({
  // 允许调用方覆盖文案，默认使用标准免责声明
  text: {
    type: String,
    default: '本系统仅供法律咨询与普法参考，不构成法律意见。如有纠纷请及时咨询专业律师。'
  }
})
</script>

<template>
  <el-alert
    class="disclaimer"
    type="warning"
    :closable="false"
    show-icon
    :title="text"
  />
</template>

<style scoped>
.disclaimer { border-radius: 12px; }
</style>
