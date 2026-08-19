# Codex `/goal` 开发手册

## 1. 为什么使用 Goal

V2 是多里程碑架构工程。`/goal` 适合保留长期完成标准和自动延续，但目标仍需有明确边界。完整约束放在仓库文档，Goal 只声明本里程碑结果、限制和验证。

## 2. 启动前检查

启动 Goal 前确认：

- 当前分支正确；
- 工作树基线清晰，已有修改已明确归属；
- 已阅读 `ARCHITECTURE.md`、相关子系统文档和 `TEST_AND_ACCEPTANCE.md`；
- 里程碑依赖已满足；
- 必要 ADR 已接受；
- 可用测试和 COMSOL 环境已知；
- Goal 不与其他写入同一文件的任务并行。

## 3. Goal 编写规则

每个 Goal 包含：

1. Outcome：完成后仓库具有什么能力；
2. Scope：允许修改的子系统；
3. Constraints：必须保持的架构不变量；
4. Verification：测试、运行和文档门槛；
5. Stop conditions：何时必须停止并请求决策。

不要把整个架构文档复制进 Goal；引用文件并强调当前里程碑。

## 4. 推荐粒度

默认一个 Goal 对应 `ROADMAP.md` 的一个里程碑。若里程碑仍超过一个可审查提交，可拆成：

- 合同与 schema；
- 核心实现；
- 集成；
- 测试和迁移。

不要用“完成整个 V2”作为第一个 Goal。

## 5. M1 Goal 模板

```text
/goal 按 docs/v2/ARCHITECTURE.md、docs/v2/TEST_AND_ACCEPTANCE.md 和 docs/v2/ROADMAP.md 的 M1 实现领域无关的 V2 Contracts 与 Agent Kernel。完成 GoalSpec、Plan、Action、Observation、RunManifest、状态机、Context Manager 接口、预算/取消、事件与 Trace；具体轴承、COMSOL 标签和修复字符串不得进入 Kernel。使用 fake tools 覆盖成功、可修复失败和预算耗尽路径，运行相关 pytest 和 ruff，并更新文档/路线图。只有本里程碑验收项全部通过才算完成；若需要改变架构不变量，先停止并新增 ADR。
```

## 6. M2 Goal 模板

```text
/goal 按 docs/v2/EXTENSION_SYSTEM.md 和 ROADMAP M2 实现动态扩展系统。支持 manifest/schema、发现、注册、启停、卸载、冲突、兼容、权限和故障隔离；建立 Function、MCP、Skill、Hook、Repair Rule、Deterministic Path、Builder、Validator、Auditor 和 Memory Adapter 接口。Kernel 不得硬编码具体扩展。新增完整合同和生命周期测试，运行相关 pytest/ruff，更新 ADR 和路线图后再完成。
```

## 7. M3 Goal 模板

```text
/goal 按 docs/v2/ARCHITECTURE.md、docs/v2/TEST_AND_ACCEPTANCE.md 和 docs/v2/ROADMAP.md 的 M3，实现 V2 通用文件编辑、沙箱执行和测试迭代闭环。完成受工作区约束的搜索/读取/最小补丁、Shell Sandbox、超时/取消、pytest/ruff runner、结构化测试失败 Observation、有限修复循环以及文件检查点或 diff rollback。使用独立 fixture 仓库验证“发现缺陷—最小修改—测试失败—依据证据修复—测试通过”完整路径，不得把轴承或 COMSOL 规则写入通用执行层。运行相关 pytest/ruff，更新路线图和必要 ADR 后再完成。
```

## 8. M4 Goal 模板

```text
/goal 按 docs/v2/MEMORY_AND_RAG.md 和 ROADMAP M4 实现 V2 多级记忆与混合 RAG。完成 MemoryRecord、VerifiedCase、RepairCase、结构化/关键词/向量/关系检索、Context Pack、provenance、晋升、quarantine、失效和删除；不兼容或未审计案例不得进入可执行基线。以检索后的执行结果而非纯文本相似度作为评估，补齐测试、迁移说明和路线图状态。
```

## 9. M5 Goal 模板

```text
/goal 按 docs/v2/COMSOL_RUNTIME.md、docs/v2/EXTENSION_SYSTEM.md、docs/v2/TEST_AND_ACCEPTANCE.md 和 ROADMAP M5，实现 COMSOL MCP Server 或等价受控工具服务。完成模型生命周期、锁、超时、取消、资源预算、A-D 阶段接口、检查点恢复、版本兼容检查、结构化异常和 artifact 管理；禁止用任意 Shell 代替受控 COMSOL 工具。先用 fake runtime 完成合同和故障测试，再运行可用的本地 COMSOL gate。若本地 COMSOL 或许可证不可用，必须记录未验证门槛，不得宣称 M5 完成。
```

## 10. M6 Goal 模板

```text
/goal 按 docs/v2/COMSOL_RUNTIME.md、docs/v2/MEMORY_AND_RAG.md、docs/v2/EXTENSION_SYSTEM.md 和 ROADMAP M6，实现诊断、动态修复规则和有限修复编排。完成错误分类器、Repair Rule 与 Solver Strategy 注册、确定性修复优先级、相容 RepairCase 检索、LLM 最小补丁合同、检查点 rollback、同错停止和重试预算。用创建顺序、无效属性、实体维度、测试失败及不可修复错误覆盖自动修复与安全停止路径；禁止原样重试和全模型无差别重写。运行相关 pytest/ruff 和可用的本地 COMSOL 回归，更新路线图与必要 ADR 后再完成。
```

## 11. M7 Goal 模板

```text
/goal 按 docs/v2/ARCHITECTURE.md、docs/v2/COMSOL_RUNTIME.md、docs/v2/TEST_AND_ACCEPTANCE.md 和 ROADMAP M7，把当前轴承能力迁移为 V2 轴承领域插件与确定性 Builder。完成 BearingSpec、ChangeSet、参数覆盖路径、圆柱滚子轴承 A-D Builder、几何/选择/接触/物理 Auditor、动态载荷延续、轴承 Skill 和 deterministic paths。优先复用已验证 V1 资产但不得把领域规则写回 Kernel；同拓扑的载荷、尺寸、滚子数量、相位和方向变更不得触发全量 LLM 重写。用真实支持范围内的参数案例运行非 COMSOL 测试及本地 COMSOL gate，并保存审计证据后再完成。
```

## 12. M8 Goal 模板

```text
/goal 按 docs/v2/ARCHITECTURE.md、docs/v2/TEST_AND_ACCEPTANCE.md 和 ROADMAP M8，实现 V2 Web、CLI 适配与可观测性。让界面展示规格解析、记忆检索、规划、工具执行、COMSOL A-D 阶段、修复、预算和审计事件，支持暂停、取消、恢复、失败反馈、artifact 下载和多轮参数变化；不得将静态演示、建模成功、求解成功和物理审计通过混为同一状态。保留现有可用入口的兼容性，用 API/事件流测试及至少一个真实端到端案例验证，更新用户文档和路线图后再完成。
```

## 13. M9 Goal 模板

```text
/goal 按 docs/v2/TEST_AND_ACCEPTANCE.md 和 docs/v2/ROADMAP.md 的 M9 完成 V2 全量验收与扩展准备。运行完整非 COMSOL 测试、核心本地 COMSOL 回归和物理审计，汇总成功率、重试次数、时间、成本、检索命中与修复有效性指标；补齐新轴承族插件指南、发布说明、迁移说明和回滚方案。逐项提供可复核证据，不得用 mock、fixture 或历史 artifact 冒充本次真实 COMSOL 运行。只有最终 Definition of Done 全部满足才标记 complete，否则保留明确的未通过项和复现命令。
```

## 14. 运行中引导

- 使用同一会话补充约束或询问状态；
- 新信息改变架构时暂停 Goal，先更新 ADR/文档；
- 工具或 COMSOL 环境暂不可用时继续可独立的确定性工作；
- 相同阻塞持续出现时报告证据，不用无意义重试消耗预算；
- 每个可验证切片完成后保持测试绿色和变更可审查。

## 15. 完成检查

Goal 完成前核对：

- Outcome 实际存在；
- 相关测试和 ruff 通过；
- 必需 COMSOL gate 有结果或明确阻塞；
- 文档、ADR、路线图和公共合同一致；
- 没有无关文件或 artifact 混入；
- 未解决风险已记录；
- 下一里程碑可以从稳定状态开始。
