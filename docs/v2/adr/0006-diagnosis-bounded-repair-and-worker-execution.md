# ADR 0006: 诊断、有限修复与同步 COMSOL handler 执行边界

- 状态：Accepted
- 日期：2026-08-21
- 决策者：项目维护者
- 替代：无
- 被替代：无

## 上下文

M6 需要把 M3 测试/文件失败、M5 `RuntimeFailure` 和 M4 `RepairCase` 统一为可扩展诊断，并在不向
Kernel 添加 COMSOL 字符串或领域分支的前提下选择 Repair Rule、Solver Strategy 和局部补丁。
同时，M5 固定快照中的同步 Builder/Path handler 可能直接进入阻塞 Java 调用；裸模型锁、资源
租约和重复 `run_id` 也会破坏取消真实性和运行所有权。

## 决策

- 新增严格 `Diagnosis` 合同：稳定顶层错误类、具体 code、失败指纹、阶段/操作、cause chain、
  retry/termination truth、影响范围、证据、兼容 checkpoint、允许修复种类、严重度和置信度。
  `DiagnosticService` 是 Kernel 外的类型化服务；它只消费结构化 `Observation`/`RuntimeFailure`。
- Repair Rule 和 Solver Strategy 是不同的动态扩展 kind。扩展对象暴露经过 Pydantic schema 校验的
  `RepairRuleContract` 或 `SolverStrategyContract`；Registry 继续负责发现、兼容、权限、启停、
  冲突、固定快照和故障隔离。固定快照提供确定性排序的候选集合；同优先级且同质量的首选规则
  产生结构化冲突，不按加载顺序覆盖。
- 修复来源顺序固定为 Repair Rule、local pattern、严格 RepairCase、LLM 局部补丁、用户决策。
  `NON_CONVERGENCE` 只解析 Solver Strategy；`RUNTIME_UNAVAILABLE`/`CANCELLED` 不改模型；未确认
  终止的 `TIMEOUT` 不自动修复；物理审计失败不能修改审计阈值。
- 每个候选必须引用触发 Observation 和诊断指纹，并受声明 scope、manifest 权限、合同权限、
  verifier、attempt budget 和 checkpoint 约束。LLM 只提交 M3 `PatchSet` 形态的 exact local diff，
  不获得新权限。复验产生新 Observation；声明的 API/solve/audit 后置门禁全部通过才成功。
- 修复前创建 checkpoint。应用异常、复验失败、同错重复、取消或预算耗尽执行 rollback；成功时
  提交或保留兼容 checkpoint。Trace 和 RunManifest 记录诊断、候选来源、RepairCase、scope、权限、
  checkpoint、验证和 rollback。
- RepairCase 必须由 M4 检索器在相符错误签名、拓扑、版本、作用域、治理状态和 artifact 引用硬
  过滤后提供。只有 executable verified RepairCase 可自动采用，采用后的执行/修复结果回写评估。
- 同步 Builder/Path handler 通过 `asyncio.to_thread` 进入受控阻塞边界，外层 BackendWorker 保持
  timeout/cancel truth。等待模型锁和资源租约时轮询 CancellationToken 与 deadline。`run_id` 的
  活动登记采用单一所有者；重复登记结构化拒绝且不能覆盖 owner token。

## 后果

新修复行为可以独立增删而不编辑 Kernel；Solver Strategy 不会混入一般建模修复；文件修改继续
复用 M3 的 sandbox、exact patch 和 rollback；历史案例不能以相似度代替复验。进程内线程仍不能
硬杀已进入 COMSOL 的 Java 调用，未确认终止会 quarantine；可回收进程 Worker 仍属于 M7/M9 前
的独立生产加固。

## 验证

- fake file/runtime/COMSOL 测试覆盖 API code、选择、pytest、solver-only、RepairCase 治理、
  scope/权限、冲突/隔离、同错、预算、checkpoint、取消、Trace 和用户可读失败；
- M5 回归覆盖同步阻塞 handler 的响应式 timeout/cancel、等待模型锁取消和重复 `run_id` 拒绝；
- 修改范围 Ruff、M1–M6 联合套件和完整仓库测试均为里程碑门禁；
- 真实 COMSOL gate 使用唯一 scratch 模型和临时 ArtifactStore，只验证安全 API/property
  错误—诊断—确定性局部修复—复验，不替代领域求解或物理验收。
