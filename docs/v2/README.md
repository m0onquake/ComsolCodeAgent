# COMSOL Agent V2 文档地图

## 文档职责

| 文档 | 负责回答的问题 |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | V2 是什么，核心组件如何协作，哪些边界不能破坏？ |
| [EXTENSION_SYSTEM.md](EXTENSION_SYSTEM.md) | Function、MCP、Skill、Hook、规则和确定性路径如何动态增删？ |
| [TOOLS_MCP_SKILLS.md](TOOLS_MCP_SKILLS.md) | Function、MCP、Skill 的执行与权限边界是什么？ |
| [MEMORY_AND_RAG.md](MEMORY_AND_RAG.md) | Agent 记住什么、如何检索、何时可信、何时失效？ |
| [COMSOL_RUNTIME.md](COMSOL_RUNTIME.md) | Agent 如何执行 COMSOL、保存检查点、诊断并修复错误？ |
| [BEARING_DOMAIN.md](BEARING_DOMAIN.md) | M7 轴承规格、最小路由、Builder、Auditor 和真实支持边界是什么？ |
| [LLM_GATEWAY_AND_PLANNING.md](LLM_GATEWAY_AND_PLANNING.md) | M7.5 如何受控接入真实 LLM、Intake、Planner、RAG 和局部修复？ |
| [WEB_CLI_OBSERVABILITY.md](WEB_CLI_OBSERVABILITY.md) | M8 如何展示事件、区分状态并提供 Web/CLI 控制？ |
| [THIRD_PARTY_COMSOL_RUNTIME.md](THIRD_PARTY_COMSOL_RUNTIME.md) | M5 评估了哪些本地/外部实现及其许可证？ |
| [TEST_AND_ACCEPTANCE.md](TEST_AND_ACCEPTANCE.md) | 如何证明代码、运行和物理结果正确？ |
| [ROADMAP.md](ROADMAP.md) | 应按什么依赖顺序开发，每个里程碑交付什么？ |
| [GOAL_PLAYBOOK.md](GOAL_PLAYBOOK.md) | 如何让 Codex 使用 `/goal` 按里程碑持续开发？ |
| [adr/](adr/README.md) | 为什么做出关键架构选择？ |

## 规范优先级

发生冲突时使用以下优先级：

1. 已接受的 ADR；
2. `ARCHITECTURE.md` 中的架构不变量；
3. 对应子系统文档；
4. `TEST_AND_ACCEPTANCE.md` 的验收门槛；
5. `ROADMAP.md` 的实施顺序。

路线图可以调整开发顺序，但不能未经 ADR 修改架构不变量。

## 开发入口

开始一个里程碑前：

1. 确认工作树基线和当前分支；
2. 阅读总体架构、相关子系统文档和测试文档；
3. 检查或新增必要 ADR；
4. 从 `GOAL_PLAYBOOK.md` 选择对应目标模板；
5. 使用 `/goal` 启动一个可独立验收的里程碑；
6. 通过测试并更新路线图状态后再进入下一里程碑。
