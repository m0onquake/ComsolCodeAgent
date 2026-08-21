# ADR 0005: COMSOL 单客户端、Worker、检查点与工具权限边界

- 状态：Accepted
- 日期：2026-08-21
- 决策者：项目维护者
- 替代：无
- 被替代：无

## 上下文

M5 需要把长时间、阻塞且具有许可证/核心资源副作用的 COMSOL 调用接入 V2。MPh 在一个 Python
进程中只能维护一个 Client；asyncio task cancellation 不能证明 Java/COMSOL 求解已经停止。
同时，检查点必须跨运行恢复但不能跨不兼容 Builder、扩展或 COMSOL 版本复用。旧 V1 工具还
包含 dict 错误和任意 Java 执行，不能直接成为 V2 Kernel 或 MCP 的权限边界。

## 候选方案

1. Kernel 直接调用旧 dict 工具，并把 task cancel 当作 COMSOL cancel。
2. 每个 Action 创建/销毁 MPh Client，以文件名作为唯一检查点兼容判断。
3. 使用类型化 Runtime 和 `MphBackendAdapter`；单客户端长生命周期、逻辑模型锁、资源租约和唯一
   运行目录；把执行放在可替换 `BackendWorker` 后；严格 checkpoint manifest；只暴露最小 MCP。

## 决策

采用方案 3。

- Runtime 合同使用严格 Pydantic schema，区分 A 输入/静态验证、B 构建/网格、C 求解、D 导出/
  审计，以及 API/代码、几何、网格、收敛、取消、超时、资源和物理审计错误。
- 每进程只创建一个长生命周期 MPh Client。所有 COMSOL 调用共享资源租约，同逻辑模型写操作由
  模型锁串行化；物理模型名和 artifact 目录包含唯一 Run ID。
- `BackendWorker` 冻结超时/取消边界。只有 worker 确认硬终止时才设置
  `termination_confirmed=true`；进程内 MPh worker 未确认终止后进入 quarantine，禁止继续租用。
  可回收子进程 worker 可以在不修改 Runtime/Kernel 合同的情况下替换它。
- B 检查点包含 schema、runtime、COMSOL、backend、Builder 和完整扩展快照版本、输入/模型摘要、
  内容哈希和 provenance。恢复先验证 manifest、模型文件哈希和所有兼容字段，任何不一致硬拒绝。
- V2 不调用旧 dict 工具；adapter 复用其 `COMSOLClient`/`ModelHandle` 与底层 MPh 能力并保留异常链。
- MCP 每个操作使用独立 schema；不公开任意 Java/Python/Shell。`execute_registered` 只能调用可信
  快照中已注册的 Builder/Path handler。Skill 不改变权限。
- cmslh5 只允许作为可选 artifact adapter，不能成为 Runtime 或 checkpoint 的强制依赖。

## 后果

正面影响：

- Kernel 保持领域无关；fake backend 可以确定性验证锁、恢复、错误和 cleanup。
- 失败保留原始 Java/Python cause chain，B 检查点可以安全复用而不会重复构建。
- 工具面可审计，任意代码执行不会因接入 MCP 而变成默认权限。

成本与风险：

- 单客户端降低单进程并发；扩展到并行 COMSOL 需要多个受许可证预算约束的 worker 进程。
- 进程内 MPh 不能可靠硬取消阻塞求解；M5 只声明 quarantine 和可替换边界。要求强制终止的部署
  必须实现进程 worker 并增加 crash/kill 回归，不能只改结果文案。
- checkpoint 兼容规则保守；升级 Builder/扩展或 COMSOL 后需要重新构建或显式迁移。

## 验证

- 合同 schema 和最小 MCP 面拒绝额外字段及任意代码能力；
- fake backend 覆盖同模型并发、超时/取消释放、B→C 恢复、损坏/不兼容 checkpoint、artifact
  哈希/provenance 和原因链；
- MPh adapter 测试证明只复用类型化 client/handle 操作；
- 真实 COMSOL smoke 使用唯一 scratch 名和临时目录验证 start/create/save/close/stop；
- 物理求解和严格审计仍是 M7/M9 的独立门，不由 M5 lifecycle smoke 替代。
