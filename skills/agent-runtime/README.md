# Python Agent Skills

当前目录有 16 项可用 Skill，标准 frontmatter 包含 name、description 与 metadata.title。SDK DefaultResourceLoader/parseFrontmatter 发现资源；公开索引提供 title、command、版本、正文大小/哈希及诊断，无正文。

每轮固定正文与 references 快照，受限 read_skill 按需分页。显式 /handle 或旧 /skill:name 的完整同版本正文进入有效模型上下文后才放行业务写入；摘要后必要时重读。自动匹配按需，当前请求选择不永久绑定课程。

GET /api/skills 返回目录，POST /api/skills/reload 重载，不影响活动运行。正文只由真实工具返回与 SDK 订阅产生过程，禁用 live 磁盘 slash 展开。旧六项和短别名采用明确正文/reference映射，不显示重复菜单。

详细规则、16项来源、适配差异、暂缓能力、旧资源备份及验收见 ../../docs/skill-migration/README.md。内部生成提示位于 generators，自动按页面类型提供，不需先读某 Skill。
