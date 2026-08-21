# V2 Function、MCP 与 Skill 边界

## 1. 目的

本文冻结 V2 工具能力的职责、权限和组合方式。Function 和 MCP 执行受控动作，Skill 只描述
工作流，Hook 执行生命周期策略；四者不能互相冒充，也不能通过自由文本获得新权限。

## 2. 能力分类

| 类型 | 执行位置 | 适用能力 | 权限来源 |
| --- | --- | --- | --- |
| Function | 可信宿主进程 | 纯计算、校验、索引、分类 | manifest + Action |
| MCP Tool | 独立服务或受控适配器 | COMSOL、外部数据和授权服务 | manifest + Action + server policy |
| Skill | 上下文说明 | 触发条件、步骤、检查清单和工具组合 | 无执行权限 |
| Hook | 生命周期边界 | 审批、阻断、Trace 和上下文注入 | manifest + event policy |

所有可执行能力必须有稳定 capability、严格输入/输出 schema、权限、版本、超时和结构化失败。
Registry 的固定快照是一次 Run 的能力事实来源。

## 3. COMSOL 最小 MCP 面

M5 提供以下类型化能力：

- `comsol.runtime_status`；
- `comsol.create_model`、`comsol.load_model`、`comsol.save_model`、`comsol.close_model`；
- `comsol.apply_parameters`；
- `comsol.execute_registered`，只接受已注册 Builder/Deterministic Path 的稳定 ID；
- `comsol.build`、`comsol.mesh`、`comsol.solve`；
- `comsol.evaluate`、`comsol.export_results`；
- `comsol.create_checkpoint`、`comsol.inspect_checkpoint`、`comsol.restore_checkpoint`；
- `comsol.cancel_run`、`comsol.inspect_failure`。

每个 capability 是独立的 `McpToolExtension`，使用对应 Pydantic 合同生成 JSON Schema。读、写、
求解权限分别声明为 `model_read`、`model_write`、`solve`，Registry 仍会对 Action 做第二次权限检查。

## 4. 明确禁止的公开能力

默认 MCP/Function 面不得包含：

- 任意 Java 代码；
- 任意 Python 代码或 `eval`/`exec`；
- 任意 Shell 字符串；
- 任意绝对输出路径或 `..` 路径；
- 未注册的 Builder、Path、Repair Rule 或 Auditor；
- 通过 Skill、检索文本或历史案例提升权限。

旧 `COMSOLClient.execute_java()` 仍是 V1 的受信内部能力，不注册到 V2 MCP。未来若受限代码补丁
确有必要，必须由可信扩展声明固定 handler、输入合同、修改范围、检查点和复验器，并经过新的
安全审查；不得增加“万能执行”工具。

## 5. 最小修改路由

COMSOL 变更按以下顺序选择：

1. `apply_parameters`：拓扑和 Builder 签名不变时只修改参数；
2. `execute_registered`：运行固定快照中的确定性 Path/Builder；
3. 受限模板或代码补丁：仅在前两者无法表达时，由后续 M6 合同控制；
4. 新拓扑候选：必须重新走静态验证、分阶段执行和物理审计。

Skill 可以描述该顺序，但实际 authority 始终来自所调用工具和 Policy。

## 6. 结果与失败

COMSOL MCP 的 `Observation.data` 是严格的 `RuntimeResult`、`Checkpoint` 或 `SessionStatus`。
失败必须包含 `RuntimeFailure`、原始原因链、阶段、错误类和可重试性。COMSOL API 成功、求解成功
和物理审计成功是不同状态，不允许 MCP adapter 把它们折叠为一个布尔值。

## 7. 会话、取消和并发

一个 Python 进程只维护一个长生命周期 MPh Client。Runtime 通过全局资源租约和逻辑模型锁串行化
写操作；每个 Run 使用唯一物理模型名和隔离 artifact 目录。

`CancellationToken` 只表示取消请求。仅当 Worker 报告 `hard_cancel=true` 时，结果才能把
`termination_confirmed` 设为 true。进程内 MPh worker 的阻塞 Java 调用不能由普通 asyncio task
可靠终止；未确认的超时/取消会将 worker 隔离，禁止复用。生产级强制终止必须使用可回收的独立
Worker 进程，M5 已把该行为放在 `BackendWorker` 边界后，不要求 Kernel 改动。

## 8. 扩展与测试要求

- MCP Tool 仍通过 M2 Registry 注册、启停、冲突解析和固定快照；
- Builder/Path/Auditor 只能通过稳定扩展 ID 注入 `MphBackendAdapter`；
- schema、权限、取消、锁、checkpoint 和错误链必须有 fake backend 测试；
- 真实 COMSOL gate 与 fake 测试分开记录；
- Skill 测试只能证明工作流选择，不能代替工具或物理验收。

该边界由 [ADR 0005](adr/0005-comsol-runtime-worker-checkpoint-and-tool-boundary.md) 固化。
