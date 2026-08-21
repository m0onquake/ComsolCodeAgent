# ADR 0007: 修复合同执行、验收治理与恢复二级故障

- 状态：Accepted
- 日期：2026-08-21
- 决策者：项目维护者
- 替代：无
- 被替代：无

## 上下文

M6 已声明 Repair Rule 与 Solver Strategy 的前置条件、兼容范围、尝试/求解/核时预算、成功判据
和回滚 checkpoint，但初版编排只执行匹配、scope、权限和 verifier。候选还可以用空
`required_gates` 让 `Observation.success=true` 直接通过。Checkpoint 创建位于候选异常边界之外，
rollback 二级失败也会覆盖原始故障并逃出编排器。这些缺口会让 M7 接触求解在不兼容或预算耗尽
后继续，并可能把未经过 solve/audit 的结果误报为成功。

## 决策

- 固定扩展快照携带 Registry 已验证的 Agent/COMSOL 运行版本。`RepairExecutionContext` 额外提供
  Builder 版本、已满足前置条件、Policy/Goal 强制门禁和已消耗 solver 预算；未知的必需兼容版本
  按不兼容处理。
- 编排器在调用扩展 handler 前执行合同前置条件、Agent/COMSOL/Builder 兼容、Repair Rule
  `max_attempts`、Solver Strategy `max_solves`/`core_hour_budget` 和 `rollback_checkpoint`。
  不满足的合同产生 `contract_rejected` Trace，不执行候选。
- `RepairCandidate.required_gates` 非空且只能增加门禁。实际门禁是错误类别最低门禁、Goal/Policy
  门禁与候选附加门禁的并集。API、pytest/Ruff、solve 和 audit 证据保持分离；M7 可以强制注入
  `solve + audit`，候选无权删除。
- `RepairExecutor.apply(candidate, limits)` 必须接收编排器生成的 `RepairExecutionLimits`。Solver
  limits 包含剩余 solve 次数、剩余核时、回滚 checkpoint、成功判据和全部门禁。复验 Observation
  必须回报对应 gates、criteria 与 solver usage，越界一律失败并回滚。
- checkpoint 创建、commit 和 rollback 都属于结构化故障边界。新增 `checkpoint_failed`、
  `commit_failed`、`rollback_failed`；rollback 失败同时保留原始故障和二级故障，并设置
  `manual_recovery_required=true`。未确认回滚后禁止尝试下一候选。
- Governed RepairCase 自动候选必须附加独立的 static/runtime 门禁，不能仅依赖记录的历史验证。

## 后果

Repair/Solver manifest 字段从描述性元数据成为运行时约束；M7 可以安全地在通用编排器上声明
接触求解预算和严格物理门禁。`RepairExecutor.apply` 是一次有意的合同加固，所有 executor 必须显式
接收 limits。回滚无法确认时运行进入人工恢复终态，不再继续自动修复。

## 验证

- 单元测试覆盖空 gates、候选降低门槛、前置条件、Builder 兼容、solve/核时预算、成功判据、
  rollback checkpoint、checkpoint 创建失败、commit 失败和 rollback 二级失败；
- M1–M6 联合测试、完整非 COMSOL 测试与修改范围 Ruff 必须通过；
- 真实 M6 smoke 继续验证 B checkpoint 恢复、局部属性修复和 API 门禁，不宣称 solve/audit 成功。
