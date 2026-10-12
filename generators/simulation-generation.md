输出一个 type=interactive 的 Scene JSON。content.html 为完整自包含 HTML/CSS/JS 文档，无 CDN、远程脚本、网络 fetch、导航或父页面访问。内容表达真实教学模型：明确变量范围、初值、单位与方程，参数或拖动驱动 Canvas/SVG 图像与可读观察值；不要用按钮只更改装饰颜色模拟实验。
变量清单 variables 与 initialState、controls 精确对应；presets 至少两个有教学差异的参数组合。所有参数控制有稳定 CSS 选择器，controls 包含所有教学高亮/显示目标和重置按钮；声明拖动能力时提供 dragProbes。窄屏可滚动并能访问主要控件。reset 回到 initialState。
必须公开 window.openmaicSimulation = {
 getState(): 返回当前 JSON 状态,
 setState(partial): 验证范围、合并参数、同步控件并重新计算图像与观察值，可返回 Promise,
 observe(): 返回仅含教学观察值的 JSON 对象（不同预设应出现可解释差异）, 
 reset(): 恢复初值并渲染,
 pause(): 暂停自动时间推进，手动参数/拖动仍有效,
 resume(): 恢复自动推进（静态实验可无操作）
}。
手动输入、拖动与老师 setState 必须共享同一状态更新函数。不能只修改 input 的 value。无需自己实现 postMessage 协议，应用会在末尾注入可信桥接器。不得覆盖桥接器、CSP 或访问 parent。
getState 必须完整反映可恢复的实验变量及自动推进所需状态。setState 支持把该完整状态恢复，observe 反映真实画面；不能依赖不可恢复的隐式全局变量。由应用桥接器管理 SNAPSHOT/RESTORE 和临时高亮、注释、显示现场，不用自己编写这些消息。controls 声明的选择器始终存在且可唯一定位，避免在渲染时删除目标节点。
生成页初始 actions 为空。sourceIds 仅引用真实资料。
variables 只声明数字参数；变量名、min/max/default/step 和对应控件值一致。固定介质等文字标签留在 HTML 中，不将字符串声明为数值变量。完整输出所有函数和闭合标签，省略可由默认值填充的无关字段，避免冗长装饰与重复代码；保留方案明确要求的全部交互。

用 read_stage(sceneId=...,path=/content/html,detail=source) 精确读取实验源码；续读带 revision。patch_stage target.sceneId + 相对 path 修改，不用重排前下标。参数/控制器/教学动作目标的 ID 保持一致。生成返回页面树而非 HTML 全文并不表示缺失；先读回再诊断。程序失败按真实 issues 修复，图像输入失败不能以文字推测视觉通过。

## 原项目规则的 Python 适配
操控必须改变可解释的机制，明确单位、科学方程、范围和假设。参数、预设、图像与observe同源；输出观察值而非装饰文本。先简单观察，再对比预测，再迁移。至少两组预设体现真实不同结果，不能只有同一状态改名字。
输入、拖动、教学setState共享一个update(partial)函数：校验→合并→同步控件→计算→绘图→更新观察。示例结构：const state={angle:30}; function update(partial){ /*校验angle范围，合并state，同步滑块，计算/绘图*/ }；getState返回完整JSON副本，setState=update，reset=()=>update(initialState)，pause/resume控制时间推进。静态实验pause/resume可无操作，但均提供函数。
不能生成自写postMessage监听器或访问parent；可信bridge负责高亮/注释/显示与SNAPSHOT/RESTORE。恢复后控件、图像、观察与getState一致，controls中选择器唯一且持续存在。选择器和变量实际拼写一致；variables只数值，文字标签留HTML。禁止远程脚本/CDN/fetch/导航。
例：折射角实验angle取0–80°，空气n=1、玻璃n=1.5，用斯涅尔关系计算折射角；presets选20°/60°，observe报告角度与介质条件。若模拟现象只是简化模型明确假设，不冒充实测。指导来自context.brief，输出完整自包含文档，无省略代码。
