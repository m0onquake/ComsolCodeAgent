# Architecture Decision Records

本目录记录 V2 中影响多个模块、难以无损回退或需要长期保持一致的架构决策。

## 使用规则

- 文件名格式：`NNNN-short-title.md`。
- 状态使用 `Proposed`、`Accepted`、`Superseded` 或 `Deprecated`。
- 一个 ADR 只处理一个核心决策。
- 已接受的 ADR 不直接改写结论；需要变更时新增 ADR，并在旧记录中标注替代关系。
- 实现代码和开发文档若与已接受 ADR 冲突，应先更新决策记录或明确说明例外。

## 索引

| 编号 | 决策 | 状态 |
| --- | --- | --- |
| [0001](0001-extension-first-agent-kernel.md) | 采用扩展优先的领域无关 Agent Kernel | Accepted |
| [0002](0002-extension-trust-lifecycle-and-resolution.md) | 扩展信任、生命周期与确定性解析策略 | Accepted |
| [0003](0003-workspace-sandbox-and-code-iteration-boundary.md) | 工作区、Shell 策略沙箱与代码迭代回滚边界 | Accepted |
| [0004](0004-memory-governance-persistence-and-retrieval.md) | 记忆治理、持久化与检索执行门禁 | Accepted |
| [0005](0005-comsol-runtime-worker-checkpoint-and-tool-boundary.md) | COMSOL 单客户端、Worker、检查点与工具权限边界 | Accepted |
| [0006](0006-diagnosis-bounded-repair-and-worker-execution.md) | 诊断、有限修复与同步 COMSOL handler 执行边界 | Accepted |
| [0007](0007-repair-contract-enforcement-and-recovery-failure.md) | 修复合同执行、验收治理与恢复二级故障 | Accepted |
| [0008](0008-controlled-model-gateway-and-llm-planning.md) | 受控 Model Gateway 与 LLM 解释/规划边界 | Accepted |

## 新建模板

复制 [TEMPLATE.md](TEMPLATE.md)，补齐上下文、决策、后果和验证方式。决策内容应尽量可通过接口约束或测试验证，而不只表达偏好。
