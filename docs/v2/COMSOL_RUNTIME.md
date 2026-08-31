# V2 COMSOL Runtime 与修复闭环

## 1. 目标

COMSOL Runtime 把 COMSOL 从最终批处理器变成 Agent 可观察、可回滚、可验证的执行环境。它提供受控工具，不把任意 Java/Python/Shell 执行直接暴露为默认能力。

## 2. Runtime 边界

Runtime 负责：

- COMSOL 连接、模型生命周期和唯一命名；
- 分阶段模型操作；
- 检查点、恢复和 cleanup；
- 超时、取消、模型锁和核心数预算；
- COMSOL 异常结构化；
- 求解和结果评估；
- artifact 生成。

Runtime 不负责理解自然语言、选择最终修复策略或宣布物理成功。

## 3. MCP/Tool 接口

M5 已实现的最小能力：

```text
comsol.runtime_status
comsol.create_model / load_model / save_model / close_model
comsol.apply_parameters
comsol.execute_registered
comsol.build / mesh / solve
comsol.evaluate
comsol.export_results
comsol.create_checkpoint / inspect_checkpoint / restore_checkpoint
comsol.cancel_run / inspect_failure
```

每个 capability 是独立的类型化 MCP Tool，声明只读/写入、幂等性、超时和 COMSOL 权限。
`execute_registered` 必须同时提交扩展 ID、版本、kind 和 capability；
`PinnedExecutionCatalog` 要求 handler 所有者是当前 Registry 固定快照中的同一扩展实例，
并在执行时再次解析和校验。不存在任意 Java/Python/Shell 工具。

MCP adapter 将 Kernel 传入的同一 `CancellationToken` 传递到 Runtime/Worker，所有公开模型操作
在 `_running` 中注册该 token，因此 `comsol.cancel_run` 可取消正在执行或等待模型锁的
`comsol.solve` 等公开请求。`comsol.restore_checkpoint` 不只校验 manifest：它使用独立
`parameters`/`specification` 重建输入摘要，通过兼容性校验后把 `.mph` 加载为请求的逻辑模型，
可继续 build/mesh/solve。
完整边界见 [TOOLS_MCP_SKILLS.md](TOOLS_MCP_SKILLS.md)。

## 4. Structured Runtime Result

```json
{
  "success": false,
  "stage": "selection_setup",
  "operation": "comsol.execute_segment",
  "model_id": "scratch_...",
  "error": {
    "class": "UNKNOWN_FEATURE",
    "exception_type": "FlException",
    "message": "Unknown feature",
    "feature_tag": "box_inner_raceway_contact",
    "property": "input",
    "source_file": "segment_C.pyfrag",
    "source_line": 149,
    "code_excerpt": "...",
    "retryable": true
  },
  "checkpoint": "artifact://.../checkpoint_B.mph",
  "artifacts": [],
  "timing": {},
  "runtime_version": {}
}
```

顶层结果必须保留嵌套异常，不允许上层只得到 `success=false, error=null`。

## 5. 阶段与检查点

| 阶段 | 完成条件 | M5 状态/检查点 |
|---|---|---|
| A Input/Static Validation | 严格合同、输入摘要和隔离目录有效 | 记录输入哈希，不保存 `.mph` |
| B Build | 参数、注册 Builder、几何/材料/物理和网格完成 | 保存兼容性绑定的 B `.mph` 与 manifest |
| C Solve | 研究/求解完成，收敛状态独立记录 | 失败时保留 B 检查点 |
| D Results/Audit | 结果评估/导出且注册 Auditor 通过 | 保存结果和 solved `.mph` artifact |

检查点记录 schema/runtime、COMSOL、MPh/backend、Builder、完整扩展快照、输入摘要、模型摘要、
模型内容 SHA-256 和 provenance。manifest 损坏、模型哈希错误或任一兼容字段不匹配均拒绝恢复。

## 6. 执行流程

1. 申请模型锁和资源预算；
2. 创建 scratch model 或恢复兼容检查点；
3. 执行单阶段动作；
4. 检查 COMSOL 结果和阶段后置条件；
5. 保存检查点；
6. 失败时返回结构化 Observation；
7. Orchestrator 分类并选择修复；
8. 从最近有效检查点复验；
9. 全部门禁通过后保存最终 artifact；
10. 关闭临时模型并释放资源。

## 7. 错误分类

| 类别 | 典型问题 | 修复边界 |
|---|---|---|
| `UNKNOWN_FEATURE` | 标签未创建或创建顺序错误 | 当前代码段依赖 |
| `INVALID_PROPERTY` | 节点不支持属性或阶段错误 | 当前节点属性 |
| `INVALID_OVERLOAD` | Python 值落入错误 Java 重载 | 类型适配层 |
| `EMPTY_SELECTION` | 选择集没有实体 | 选择定位器/几何证据 |
| `ENTITY_DIMENSION` | 实体维度缺失或不匹配 | 当前选择或特征 |
| `PAIR_BINDING` | 接触对 source/destination 无效 | 接触与命名选择 |
| `GEOMETRY_FAILURE` | 布尔、分割、装配失败 | A/B Builder 与参数 |
| `MESH_FAILURE` | 目标选择或体网格失败 | 网格阶段 |
| `NON_CONVERGENCE` | 牛顿、接触或参数步失败 | 初始化/延续/求解器 |
| `PHYSICS_AUDIT_FAILURE` | 反力、载荷或接触力不闭合 | 物理合同与边界条件 |
| `RUNTIME_UNAVAILABLE` | 许可、服务、连接或版本问题 | 环境，不修改模型代码 |
| `CANCELLED` | 用户/策略发出取消请求 | Worker cleanup；不等同于硬终止 |
| `TIMEOUT` | 阶段或 Worker 超过预算 | 释放 host lease；未确认 Worker 隔离 |
| `RESOURCE_UNAVAILABLE` | 许可证、核心、会话或 worker 不可租用 | 环境/调度，不修改模型 |

这些具体 code 归入稳定顶层类别：`api_code_error`、`geometry_error`、`mesh_error`、
`solve_or_convergence_error`、`cancelled`、`timeout`、`resource_error` 和
`physics_audit_failure`。顶层用于编排，具体 code 用于 M6 Repair Rule 匹配。

## 8. 修复决策

顺序固定为：

1. 确定性 Repair Rule；
2. 本地 API/属性模式；
3. 已验证 RepairCase；
4. LLM 受限局部补丁；
5. 用户决策或结构化失败。

禁止行为：

- 同一输入原样重试；
- API 错误触发全模型重写；
- 不收敛时未经证据改变几何或物理模型；
- 物理审计失败后仅调整报告阈值；
- 从失败模型晋升 verified memory。

## 9. 有限修复循环

```python
for stage in execution_plan:
    checkpoint = latest_compatible_checkpoint(stage)
    candidate = prepare_stage(stage)

    for attempt in repair_budget(stage):
        static = validate(candidate)
        if not static.success:
            candidate = repair(static, candidate)
            continue

        runtime = execute(stage, candidate, checkpoint)
        if runtime.success and verify_postconditions(runtime):
            checkpoint = save_checkpoint(stage)
            break

        diagnosis = classify(runtime)
        candidate = select_scoped_repair(diagnosis, candidate)
    else:
        return fail_with_evidence(stage)
```

默认每阶段最多三次尝试，其中 LLM 补丁最多两次。具体预算通过 Policy 配置。

## 10. 求解器路径

求解必须与建模修复分离：

1. 验证载荷面积和约束；
2. 建立接触初始化；
3. 计算目标相关的动态载荷延续计划；
4. 分块求解并继承收敛解；
5. 记录已返回参数步；
6. 目标步失败时使用声明式 solver strategy；
7. 达到预算后保留最后收敛检查点并反馈。

Solver Strategy 也是动态扩展，必须声明适用错误、前置条件、修改范围和复验指标。

## 11. 物理审计

至少验证：

- 目标载荷步存在；
- 实际施加载荷与目标一致；
- 支承反力闭合；
- 接触力闭合；
- 弱弹簧/稳定项占比；
- 载荷区方向；
- 选择面积与预期几何一致；
- 应力和位移有限；
- 原生图像、求解后 MPH 和摘要存在。

具体阈值由领域 Auditor 和版本化物理合同定义。

## 12. 沙箱、安全和并发

- 一个模型写操作同时只属于一个 Run；
- 使用唯一 scratch model 和 artifact 目录；
- 禁止以未解析环境变量或宽泛路径执行清理；
- Shell 与 COMSOL Java 执行分权；
- 长运行支持取消和超时；
- 失败模型保留最小诊断 artifact；
- 日志过滤密钥、授权信息和不必要的大数组；
- MPh 每个 Python 进程只能维护一个 Client；M5 使用单个长生命周期会话、资源租约和显式队列；
- 普通 asyncio cancellation 只表示请求，不证明 COMSOL 已终止；只有 Worker 确认硬终止才能如此
  记录，未确认的进程内 MPh worker 必须 quarantine；
- 需要可靠强制终止和多会话并行时，使用可回收进程 Worker，并受 COMSOL 许可证/核心预算约束。

## 13. Runtime 验收

- 每个工具 schema 可验证；
- 嵌套异常完整上浮；
- 检查点兼容性可拒绝错误恢复；
- 取消/超时释放模型锁；
- 已知错误可从最近检查点局部复验；
- 同错重复受到限制；
- API 成功、Solve 成功和 Audit 成功状态分离；
- Trace 能重建一次运行的关键动作。

## 14. M5 实现映射

M5 位于 `comsol_agent/v2/runtime/comsol/`：

- `contracts.py`：运行请求、阶段、结果、Artifact、Checkpoint、Session 和错误合同；
- `backend.py`：`ComsolBackend`/`BackendWorker` 边界、明确取消语义的 in-process executor，以及
  复用 V1 `COMSOLClient` 的 `MphBackendAdapter` 和绑定 Registry 固定快照的
  `PinnedExecutionCatalog`；
- `artifacts.py`：每 Run/Model 隔离目录、原子 JSON manifest、SHA-256 与 provenance；
- `service.py`：长生命周期会话、唯一物理名、模型锁、资源租约、A-D 编排、B→C 恢复、cleanup、
  取消和失败索引；
- `mcp.py`：17 个独立 schema 的最小 MCP Tool extensions，通过 M2 Registry 接入 Kernel，
  并将 Kernel cancellation token 端到端传给 Runtime；
- `scripts/run_v2_comsol_smoke.py`：独立的真实 COMSOL lifecycle gate。

本地复用和外部调研见 [THIRD_PARTY_COMSOL_RUNTIME.md](THIRD_PARTY_COMSOL_RUNTIME.md)，架构决策见
[ADR 0005](adr/0005-comsol-runtime-worker-checkpoint-and-tool-boundary.md)。M5 不包含领域 Builder、
Solver Strategy 或轴承物理 Auditor；这些由 M6/M7 扩展注入，严格物理回归属于 M7/M9。

## 15. M6 接入与 M5 残余加固

- `DiagnosticService.from_runtime()` 保留 `RuntimeFailure` 的 code、cause chain、stage、operation、
  compatible B checkpoint 和 `termination_confirmed`，不在 Kernel 解析 COMSOL 文本；
- C 阶段失败由 RepairOrchestrator 选择 scope 受限的规则或 Solver Strategy，并分别复验 API、solve
  和 audit gate；checkpoint 损坏或不兼容仍由 Runtime 硬拒绝；
- 同步 Builder/Path handler 改为在线程边界执行，事件循环可及时观察 BackendWorker 的 timeout 和
  cancellation。线程不能证明硬终止，未确认终止仍 quarantine；
- 模型锁和资源租约等待现在观察 CancellationToken 与 deadline；等待期取消不再依赖前序长任务
  完成；
- 所有公开运行使用单一 `run_id` owner。并发重复 ID 返回 `RESOURCE_UNAVAILABLE`，不会覆盖或
  提前移除原 owner token。

M6 真实门只触发安全、可预测的 API/property 错误并局部修复，不运行轴承物理回归。执行与修复
边界见 [ADR 0006](adr/0006-diagnosis-bounded-repair-and-worker-execution.md)。

## 16. M6 P0 合同与恢复故障加固

- `RepairExecutionContext` 提供当前 Agent/COMSOL/Builder 版本、已满足前置条件、Goal/Policy
  强制门禁以及已消耗 solve/核时；未知的必需版本不视为兼容；
- Solver Strategy 只有在 preconditions、兼容、剩余 solve/核时和声明的 rollback checkpoint 全部
  满足时才会执行。Executor 收到剩余额度，复验必须返回独立 gates、success criteria 和 usage；
- 验收要求是错误类别最低门禁、Goal/Policy 门禁和候选附加门禁的并集。候选不得以空 gates 或
  少声明 solve/audit 降低成功标准；
- checkpoint 创建、commit 与 rollback 失败分别产生结构化终态。rollback 二级失败保留原始错误，
  标记 `manual_recovery_required` 并禁止继续自动修复。

决策见 [ADR 0007](adr/0007-repair-contract-enforcement-and-recovery-failure.md)。

## 17. M7 轴承运行时接入

M7 不扩大 MCP 面。轴承 Builder 和 deterministic paths 继续通过 `PinnedExecutionCatalog` 绑定
固定快照；Skill 没有执行权限。Geometry/Selection/Contact/Physics Auditor 分别返回结构化门禁，
Runtime 仍区分 B configured checkpoint、C solve 和 D strict audit。

方向感知载荷延续声明目标序列、分块、最大 solve、B rollback checkpoint 和成功判据。尺寸、
游隙、滚子数量或相位变化不在已构建几何上伪装成纯参数求解，而由确定性 Builder 重建；载荷、
方向和 solver 参数可复用相容 B checkpoint，但必须重新 solve/audit。真实 gate 和证据格式见
[BEARING_DOMAIN.md](BEARING_DOMAIN.md)。

`solver_relative_tolerance` 不是 model parameter；COMSOL 6.2 的 Stationary solver feature 使用
`stol`。参数路径和 Builder 执行都必须对每个目标 solution sequence 写入并读回该属性，
空绑定、部分绑定或读回不一致均是 gate 失败。结果评估必须从目标 `radial_load`
参数值选择 solution number，不得使用“最后一个数组元素”或绘图层序号代替数据集/解绑定。

### M7.5.1 参数覆盖恢复语义

`parameter_override` 必须同时提供完整 previous/requested spec、相容 B checkpoint、
固定 parameter path 和 continuation path。Runtime 首先用 previous 物理输入验证检查点，
再执行局部覆盖和新的 C/D；A/B 必须记录为 skipped。恢复兼容性排除 provenance、
build/topology 派生字段，但仍强制 model、stage、COMSOL/runtime/backend、Builder 和
snapshot 版本一致。

进程内 MPh 调用的强取消风险仍存在：2026-08-24 的 `-Y / 10 N` 真实覆盖运行
正确跳过 A/B，但 C 在 1200 s 超时且 `termination_confirmed=false`。该运行是失败
证据，不得用于声明 -Y/10 N 物理支持；也说明生产环境仍需要可回收进程
Worker 才能提供确定硬取消。

## 18. M9 可回收进程 Worker

`ProcessComsolBackendProxy` 通过 spawn 子进程持有完整 MPh backend，并只接受类型化 backend RPC。
spawn-safe factory 在子进程内构建 Registry snapshot、PinnedExecutionCatalog 和 Auditor；父子版本
不一致时在 COMSOL 前拒绝。`RecyclableProcessWorkerExecutor` 只有在 terminate/join/kill 确认子进程
退出后才报告硬取消成功，后续调用创建新 PID，不复用旧模型状态。

确定性测试已覆盖完整 A–D child-owned 状态、阻塞调用取消和进程重建。2026-08-26
的真实 gate 在 C solve `running` 后取消，确认子进程终止、无 solved artifact，且后续新 COMSOL
lifecycle 通过；[ADR 0010](adr/0010-durable-sessions-and-recyclable-comsol-worker.md) 因此 Accepted。
