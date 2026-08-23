# ADR 0009: Pinned Plan Execution Bridge

- Status: Accepted
- Date: 2026-08-24

## Context

M7.5 的首次真实 gate 将 LLM Intake/Planner 与旧 COMSOL gate 串联，但 Plan 没有经
Agent Kernel、固定 Registry snapshot 和 M5 Runtime 执行。这能证明两个子系统分别可用，
不能证明 Agent 端到端边界或 Planner 产生的 capability 真实可执行。

## Decision

Planner 只能从不可变 `ExtensionSnapshot` 构造 capability catalog，并生成一个已注册
Function Action。Action 固定所有必需 Function、Builder、deterministic path 和 Auditor 的
ID/version/kind/capability。`RegistryToolExecutor` 解析 Function，领域工作流再校验全部
pin 后调用 M5 Runtime。Kernel 只保留通用 Action/Observation/audit 记录，不引入轴承规则。
失败 Observation 在 Tool 边界由 `ObservationRepairRouter` 转为 M6 Diagnosis 并调用有限
RepairOrchestrator；候选仍由扩展提供，没有候选或 termination 未确认时安全停止。

Parameter override 必须携带完整 previous/requested spec 和相容 B checkpoint；Runtime 恢复
B 后执行固定 override/continuation path，并且只重跑 C/D。

## Consequences

- 伪造版本、capability、schema 或权限在 COMSOL 前失败。
- LLM token 只用于 Intake/Planner；COMSOL 模型由确定性 Builder/Path 生成和修改。
- 参数变更可证明没有重建 A/B，但仍必须通过新的 C/D 才能声明物理支持。
- 进程内 MPh 阻塞调用仍无法保证硬取消，不属于此桥接的权限扩张。
