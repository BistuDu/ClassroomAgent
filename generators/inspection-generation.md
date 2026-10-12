检查必须基于当前指纹的真实正式渲染器截图和程序结果。程序检查不是视觉判断，看到截图之后才可以记录 visual passed。
程序检查应在讲稿和音频就绪后验证音频覆盖。截图 renderFingerprint 仅依赖实际画面；视觉结论 visualReviewFingerprint 还依赖讲稿语义、动作目标及引用事实；程序 programFingerprint 包含语音配置、文件与覆盖。仅补音频/改音色不使同画面的截图和视觉结论过期；仅改讲稿可复用画面，但需要重新判断图文讲解一致性并记录视觉结论。查看布局层次、文字与公式完整性、图示真实性、配图和讲稿一致性、留白及实验控件可达性。
实验检查涵盖初值、至少两组声明预设、手动参数操作、声明的拖动交互和 reset。比较 observe 的真实结果，无法验证科学正确性时在 uncovered 中写明；不把截图理解称为官方评测。
失败定位到具体字段/元素，用 patch_stage 或 generate_scene 修正，保留已有真实成果。每页每次运行最多两轮修正，达到上限报告问题或询问用户。课程仅在当前版本的 program 与 visual 均通过、无缺页、讲稿音频有效时完成。
每个方案页的页面生成和动作生成分别最多尝试三次（初次加两次重试），首次生成失败也计数；GENERATION_BUDGET 或 REPAIR_BUDGET 后本轮停止该页生成，不用更名、删除重插或换工具绕过限制。无效修改不消耗成功修正次数；仅看了截图必须调用 check_scene(mode=visual) 保存结论，不能用聊天说明充当报告。

check_scene(mode=program) 不传 passed/findings/snapshotId，结论由真实执行产生；设施失败 executed=false/isError=true，不等于检查完成发现内容问题。visual 必须传当前目标的 snapshotId、passed、findings，不能引用别页或过期画面。报告的 issues/coverage/uncovered 指明实际证据与未验证范围。旧指纹报告保留旧规则，不能凭空升级为新版有效。制作模型拒绝图片时停止视觉判断并报告 MODEL_IMAGE_UNSUPPORTED。
