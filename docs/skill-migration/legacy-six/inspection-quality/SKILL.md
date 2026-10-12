---
name: inspection-quality
description: 页面程序检查、真实截图视觉检查、实验交互检查、音频覆盖和课程就绪状态。验收或修复页面时读取。
---

# 质量检查

程序检查不是视觉判断。先用 `render_scene_preview` 获取当前正式渲染器的 snapshot，再调用 `check_scene(mode=program)` 和 `check_scene(mode=visual)`。visual 必须引用当前目标的 snapshotId、passed、findings；不能引用别页或过期画面。

检查布局层次、文字/公式完整性、图示真实性、配图和讲稿一致性、留白与控件可达性。互动实验要验证初值、至少两组 presets、手动参数操作、声明的拖动和 reset，并比较真实 observe 结果。无法验证的范围写入 uncovered。

程序检查还要确认讲稿和音频覆盖。只补音频不使同画面视觉结论过期；改讲稿需重新判断图文一致性。失败定位到具体字段或元素，用 `patch_stage`/`generate_scene` 修正并重检；不能删除问题记录或用聊天文字代替报告。课程只有当前 program、visual、页面、讲稿和有效音频都满足时才算就绪。
