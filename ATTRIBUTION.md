# 来源与适配说明

## 上游项目

- 项目：[THU-MAIC/OpenMAIC](https://github.com/THU-MAIC/OpenMAIC)。
- 上游许可：MIT；本仓库保留上游 `Copyright (c) 2026 THU-MAIC` 与完整许可文本，见 [LICENSE](LICENSE)。
- 本仓库是独立的 Python 后端、Pi SDK 制作桥接与 React 课堂应用，不是上游官方发行版。

## 迁移资源

- 16 个内置 Skill、参考资料及生成规则：来源和适配记录见 [Skill manifest](docs/skill-migration/manifest.json)。其中的 `OpenMAIC-main/...` 是上游来源记录，不是运行时本地依赖。
- 教师、同学、导演和发言规则：见 [课堂提示词来源](backend/classroom-prompt-resources/README.md) 与 [manifest](backend/classroom-prompt-resources/manifest.json)。`.original.md` 保留相关上游片段，以便追溯适配。
- 历史六项 Python 制作规范备份：`docs/skill-migration/legacy-six/`，不属于当前可发现的 Skill 根目录。

## Python 适配边界

制作由 Pi Agent SDK 调用 Python 业务工具；实时课堂由 LangGraph 运行。页面、教学动作、配音独立生成。页面文档、基础单选题、数值实验协议、当前页工具权限、版本校验与质量状态按本仓库契约实现。具体区别见 [Skill 迁移说明](docs/skill-migration/README.md) 和 [README](README.md)。

## 第三方依赖

Python 与 Node 依赖分别列于 `pyproject.toml`、`uv.lock`、`package.json` 和 `package-lock.json`。各依赖保留各自许可，本仓库的许可不替代第三方依赖的许可。运行数据、个人材料、供应商密钥与原项目完整源码不随仓库发布。
