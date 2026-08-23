# V2 测试与验收

## 1. 原则

V2 使用分层证据证明完成：合同测试证明接口，沙箱测试证明执行闭环，COMSOL 测试证明 API 和求解，物理审计证明结果可信。任何一层通过都不能替代下一层。

## 2. 测试层级

### 2.1 Contract Tests

- GoalSpec、EngineeringSpec、Action、Observation 和 RunManifest schema；
- Extension manifest 与兼容性；
- MCP/Function 输入输出；
- MemoryRecord、VerifiedCase 和 RepairCase；
- 版本升级和失效策略。

### 2.2 Unit Tests

- ChangeSet 分类；
- 最小修改路由；
- 依赖拓扑排序；
- Java 重载和值类型适配；
- 错误分类；
- Repair Rule 匹配、作用域和预算；
- Deterministic Path DAG；
- RAG 过滤、重排和引用复验；
- 记忆晋升/降级；
- Hook 和扩展故障隔离。

### 2.3 Sandbox Integration Tests

使用 fake MCP/COMSOL Runtime 验证：

- Agent Loop 的 Action—Observation—Repair；
- 文件最小 diff；
- 命令超时、取消和权限拒绝；
- 阶段检查点与恢复；
- 重试预算和同错停止；
- Trace、事件和 Web 状态；
- 无 LLM 条件下的确定性路径。

### 2.4 Local COMSOL Tests

- A-D 各阶段独立执行；
- 模型生命周期和锁；
- 选择集实体数量/面积；
- 接触对绑定；
- 网格和研究配置；
- 初始化和载荷延续；
- 结构化异常；
- 检查点恢复；
- 结果导出。

### 2.5 Physical Acceptance Tests

- 目标载荷与实际载荷；
- 支承反力平衡；
- 内外接触力平衡；
- 稳定项占比；
- 对称性和载荷方向；
- 应力/位移有限性；
- 原生结果图和 MPH 完整性。

## 3. 常用本地命令

```bash
.venv/bin/python -m pytest tests/test_core.py -q
.venv/bin/python -m pytest tests/test_bearing_domain.py -q
.venv/bin/python -m pytest tests/test_web.py -q
.venv/bin/python -m pytest -q
.venv/bin/ruff check comsol_agent tests scripts
```

开发中先运行最小相关集合，里程碑完成前运行完整非 COMSOL 套件。真实 COMSOL 回归使用单独标记、脚本或 CI 环境，不能隐藏在普通快速单元测试中。

## 4. 核心回归场景

| 场景 | 主要目的 |
|---|---|
| 基准 12 滚子、+X、约 10.1 N | 基础 Builder 和严格审计 |
| 同拓扑约 101 N | 参数复用而非全量生成 |
| 15° 周向相位 | 几何和选择相位一致 |
| +Y、-X、-Y | 载荷、约束和载荷区方向 |
| 合法尺寸组合 | 几何关系与 Builder 参数化 |
| 滚子数量变化 | 循环标签、选择、接触和探针 |
| 创建顺序错误 | `UNKNOWN_FEATURE` 确定性修复 |
| 无效结果属性 | `INVALID_PROPERTY` 修复 |
| 空选择集 | 明确失败或受限修复 |
| 非线性不收敛 | 进入 solver strategy，不重写几何 |
| 不兼容历史案例 | RAG 拒绝错误复用 |
| 扩展禁用/冲突 | Registry 行为与错误隔离 |

## 5. 里程碑完成门槛

一个里程碑只有同时满足以下条件才算完成：

- 文档中的交付物已实现；
- 新增或修改合同有测试；
- 相关单元和集成测试通过；
- Ruff 对修改范围无新增问题；
- 必需 COMSOL gate 已运行，或明确记录环境阻塞；
- Trace/错误输出足以诊断失败；
- 相关文档、路线图和 ADR 已更新；
- 没有把未验证候选写入 verified memory；
- 变更范围可审查且不包含无关 artifact。

## 6. VerifiedCase 晋升门槛

除上述工程门槛外，正式案例还必须：

- 使用最终目标规格和目标载荷；
- COMSOL 全阶段成功；
- 返回目标参数步；
- 严格物理门禁全部通过；
- artifact 可读取且哈希记录完整；
- 版本和来源完整；
- 运行没有未解决的高等级警告。

## 7. 失败标准

以下情况不得声明完成：

- 仅静态生成成功；
- COMSOL 创建成功但未求解；
- 求解成功但没有目标参数步；
- 有应力图但载荷/反力不平衡；
- 测试通过依赖旧 artifact 或隐藏状态；
- 自动修复仅改变阈值或忽略异常；
- 需要真实 COMSOL 验证但只运行 mock；
- 目标要求动态扩展，但实现仍依赖 Kernel 硬编码。

## 8. 质量指标

- 参数请求全量代码再生成率，目标 0；
- 首次 COMSOL 阶段成功率；
- 自动修复后成功率；
- 物理审计通过率；
- 平均 LLM 调用数和修复次数；
- 同错重复率；
- 检查点节省的重建时间；
- RAG Top-k 命中、采用后成功率和误复用率；
- 扩展加载失败隔离率；
- 用户收到首个有效阶段反馈的延迟。

## 9. 最终 Definition of Done

V2 达到可用状态至少要求：

- Kernel、扩展系统、工具层和 Trace 完整；
- Function、MCP、Skill、Hook 可注册和启停；
- 动态 Repair Rule 与 Deterministic Path 可加载；
- 文件编辑、沙箱执行和测试迭代闭环可用；
- 多级记忆、混合 RAG、晋升和失效可用；
- COMSOL 分阶段运行、检查点和结构化错误可用；
- 支持范围内轴承走确定性 Builder；
- 参数修改不触发全量自由生成；
- 规定的 COMSOL 和物理回归通过；
- Web/CLI 明确展示阶段、修复、结果和失败原因。

## 10. M1 验收记录

日期：2026-08-20。

- `tests/test_v2_kernel.py` 使用不含领域逻辑的 fake executor 覆盖一次直接成功、一次可修复失败后
  成功、一次修复预算耗尽，以及取消、工具异常结构化、状态机、事件隔离和合同 schema；
- `.venv/bin/python -m pytest tests/test_v2_kernel.py -q`：12 passed；覆盖预算耗尽和执行中取消时
  active step 收敛为 `failed`，未开始步骤保持 `pending`；
- `.venv/bin/python -m pytest -q`：242 passed，1 个既有依赖弃用 warning；
- `.venv/bin/ruff check comsol_agent/v2 tests/test_v2_kernel.py`：通过；
- 全仓 `.venv/bin/ruff check comsol_agent tests scripts` 仍报告 3135 个 M1 之前已存在于旧代码和
  测试中的问题。本里程碑未改写这些无关文件，修改范围没有新增 Ruff 问题；
- M1 只验收 fake-tool Kernel 闭环，不要求本地 COMSOL 或物理 gate，也未发生 verified memory
  晋升；
- 实现保持 ADR 0001，不需要新增 ADR。

## 11. M2 验收记录

日期：2026-08-20。

- `tests/test_v2_extensions.py` 覆盖 manifest/schema、可信发现与动态加载、配置 schema、Agent/
  COMSOL 兼容、权限上限与动作权限、12 种扩展 kind 的注册/启停/健康/卸载、租约式固定快照、
  重复 ID/版本、缺失和反向依赖、路径 capability 依赖与 provider 卸载保护、结构化冲突、
  显式选择、`sys.path`/`sys.modules` 同名模块遮蔽拒绝、阻塞 deactivation 并发隔离、
  activation/handler 故障隔离，以及通过 Registry Function 执行完整 Kernel 流程；
- `.venv/bin/python -m pytest tests/test_v2_extensions.py tests/test_v2_kernel.py -q`：41 passed；
- `.venv/bin/python -m pytest -q`：271 passed，1 个既有 Starlette/httpx 弃用 warning；
- `.venv/bin/ruff check comsol_agent/v2 tests/test_v2_extensions.py tests/test_v2_kernel.py`：通过；
- 全仓 Ruff 继续受 M2 之前的旧代码问题影响；M2 修改范围没有新增问题；
- M2 是纯合同、Registry 和 fake extension 验收，不需要本地 COMSOL 或物理 gate，也未发生
  verified memory 晋升；
- 新增并接受 ADR 0002，固化可信加载、权限/兼容硬拒绝、固定快照和冲突策略。

## 12. M3 验收记录

日期：2026-08-20。

- `tests/test_v2_code_tools.py` 覆盖工作区搜索/读取、绝对路径与 `..` 越界、符号链接拒绝、
  exact replacement 冲突、文件 checkpoint/rollback、executable/argv profile 拒绝、命令超时、
  执行中取消、真实大输出触顶时的流式保留预算与进程终止、pytest JUnit 结构化失败、Ruff JSON
  diagnostics 和 Kernel ToolExecutor 错误归一化；
- 独立 `tests/fixtures/m3_code_repo/` 的临时副本完成“发现缺陷—lowercase 最小补丁—pytest 暴露
  空值缺陷—修复策略引用该 Observation—第二次最小补丁—pytest 通过”的完整路径；另一个案例
  在修复预算为零时证明候选补丁被恢复；
- `.venv/bin/python -m pytest tests/test_v2_code_tools.py -q`：14 passed；
- `.venv/bin/python -m pytest tests/test_v2_kernel.py tests/test_v2_extensions.py
  tests/test_v2_code_tools.py -q`：55 passed；
- `.venv/bin/python -m pytest -q`：285 passed，1 个既有 Starlette/httpx 弃用 warning；
- `.venv/bin/ruff check comsol_agent/v2 tests/test_v2_kernel.py tests/test_v2_extensions.py
  tests/test_v2_code_tools.py`：通过；
- 全仓 `.venv/bin/ruff check comsol_agent tests scripts --statistics` 报告 3136 个 M3 之前或当前
  无关用户工作树中的旧问题；M3 修改范围没有新增 Ruff 问题；
- M3 不调用 COMSOL，不需要本地求解或物理 gate，也没有将候选写入 verified memory；
- 新增并接受 ADR 0003；实现提交为
  `477e2102d950b9e4ea3d4bfac87c0e092dbbb9d9`，领域中立守卫提交为
  `2fe8e1789bc366b7cc37ee9effad08ffbc8a8619`，流式输出资源边界修复提交为
  `3d53a65015de7e15e53135948a6622f60a7bc190`。

## 13. M4 验收记录

日期：2026-08-21。

- `tests/test_v2_memory.py` 覆盖 MemoryRecord/VerifiedCase/RepairCase 严格 schema、Working/Session
  与长期层级隔离、强制 quarantine、证据晋升、治理绕过拒绝、失效、删除 tombstone、原子持久化、
  迁移幂等性，以及不完整 provenance、未过物理门禁和未 runtime 复验案例的晋升拒绝；
- 混合 RAG 覆盖兼容案例命中、拓扑和 COMSOL 版本硬拒绝、结构化/BM25/向量/关系通道、artifact
  丢失降级为 `needs_revalidation`、RepairCase 错误签名精确匹配、invalidated 案例拦截，以及查询
  版本信息不完整时拒绝 active API Rule 进入 hit/Context Pack；
- Context Pack 验证一个主案例、最多两个辅助案例、角色/provenance 和 artifact 引用，不内联历史
  基线代码；RetrievalEvaluator 使用采用后的执行、严格审计和修复结果，并回写历史采用成功率；
- `.venv/bin/python -m pytest tests/test_v2_memory.py -q`：17 passed；
- `.venv/bin/python -m pytest tests/test_v2_kernel.py tests/test_v2_extensions.py
  tests/test_v2_code_tools.py tests/test_v2_memory.py -q`：72 passed；
- `.venv/bin/python -m pytest -q`：302 passed，1 个既有 Starlette/httpx 弃用 warning；
- `.venv/bin/ruff check comsol_agent/v2 tests/test_v2_memory.py scripts/migrate_v2_memory.py`：通过；
  全仓 `--statistics` 仍报告 3136 个 M3 已记录的旧问题，M4 修改范围没有新增问题；
- M4 不调用 COMSOL，真实求解和物理回归不适用；测试中的严格审计证据只验证 promotion policy，
  没有将 fixture 或历史 artifact 写入持久 verified memory；
- 新增并接受 ADR 0004；实现提交为 `99b38d662b574c61aee71bc3bc7b8431af0077da`。

## 14. M5 验收记录

日期：2026-08-21。

- `tests/test_v2_comsol_runtime.py` 使用严格合同和 async fake MPh backend 覆盖 JSON Schema/额外
  字段拒绝、API 错误原因链、同模型并发锁、确认/未确认的超时和取消、host 资源释放、worker
  quarantine、B→C 恢复且不重复 build、不兼容/损坏 checkpoint、artifact 隔离/哈希/provenance、
  参数补丁、MPh 类型化 adapter 和不含任意代码的最小 MCP surface；追加覆盖公开 MCP
  solve→cancel 的端到端 token、MCP restore 真实加载后继续 solve，以及 Builder handler
  所有者/ID/version/kind/capability 与 Registry 固定快照的绑定和拒绝路径；
- `.venv/bin/python -m pytest tests/test_v2_comsol_runtime.py -q`：15 passed；
- `.venv/bin/python -m pytest tests/test_v2_kernel.py tests/test_v2_extensions.py
  tests/test_v2_code_tools.py tests/test_v2_memory.py tests/test_v2_comsol_runtime.py -q`：87 passed；
- `.venv/bin/python -m pytest tests/test_core.py -q`：203 passed；
- `.venv/bin/python -m pytest tests/test_bearing_domain.py -q`：14 passed；
- `.venv/bin/python -m pytest tests/test_web.py -q`：13 passed，1 个既有依赖弃用 warning；
- `.venv/bin/python -m pytest -q`：317 passed，1 个同样的既有 warning；
- `.venv/bin/ruff check comsol_agent/v2 tests/test_v2_kernel.py tests/test_v2_extensions.py
  tests/test_v2_code_tools.py tests/test_v2_memory.py tests/test_v2_comsol_runtime.py
  scripts/run_v2_comsol_smoke.py`：通过；
- 全仓 `.venv/bin/ruff check comsol_agent tests scripts`：3136 个 M4 已记录的既有旧代码/当前无关
  用户工作树问题；M5 修改范围没有新增问题；
- `.venv/bin/python scripts/run_v2_comsol_smoke.py --version 6.2 --cores 1`：在适配器合同加固后重跑，
  真实 MPh 1.3.1 +
  COMSOL 6.2 start/create/save/close/stop 通过；唯一 scratch model、临时隔离目录、19,952-byte MPH
  和 SHA-256 均由本次运行产生，临时目录随后清理；
- 该真实 gate 验证 M5 会话/模型/artifact 生命周期，不声明领域求解或物理成功；轴承 Builder、
  solver strategy 和严格物理审计仍分别属于 M6/M7/M9；
- 新增并接受 ADR 0005，记录单客户端、Worker、取消真实性、checkpoint 兼容和最小工具权限边界；
  未发生 verified memory 晋升。
- 原 M5 commit 为 `9fb4bcbd52f331b7fac434286c2b3884b2414c50`；本记录中的 P0 加固以
  独立 follow-up commit 交付。

## 15. M6 验收记录

日期：2026-08-21。

- `tests/test_v2_repair.py` 使用 fake file/runtime/COMSOL 与真实 M3 Workspace 覆盖
  `UNKNOWN_FEATURE`、`INVALID_PROPERTY`、`INVALID_OVERLOAD`、`ENTITY_DIMENSION`、
  `EMPTY_SELECTION` 安全停止、pytest exact patch、Solver Strategy 独占路由、环境/取消/超时、
  物理审计阈值保护、同错、预算、checkpoint/rollback、严格 RepairCase、动态禁用/删除、冲突、
  handler 隔离、Trace 和 RunManifest；17 passed；
- `tests/test_v2_comsol_runtime.py` 增至 18 passed，新增同步阻塞 Builder/Path handler 的响应式
  timeout/cancel、等待模型锁取消和重复 `run_id` owner 拒绝；
- `.venv/bin/python -m pytest tests/test_v2_kernel.py tests/test_v2_extensions.py
  tests/test_v2_code_tools.py tests/test_v2_memory.py tests/test_v2_comsol_runtime.py
  tests/test_v2_repair.py -q`：108 passed；
- core 203、bearing domain 14、web 13 passed；完整 `.venv/bin/python -m pytest -q`：338 passed，
  1 个既有 Starlette/httpx 弃用 warning；
- `.venv/bin/ruff check comsol_agent/v2 tests/test_v2_repair.py tests/test_v2_comsol_runtime.py
  scripts/run_v2_comsol_smoke.py scripts/run_v2_repair_smoke.py`：通过；附件要求的含整个 `scripts`
  命令仍报告 1607 个既有旧脚本问题，M6 修改范围没有新增 Ruff 问题，未批量改写无关脚本；
- `.venv/bin/python scripts/run_v2_repair_smoke.py --version 6.2 --cores 1`：真实 MPh 1.3.1 +
  COMSOL 6.2 门通过。唯一 scratch 模型触发真实 `FlException: Unknown property`，分类为
  `INVALID_PROPERTY`，保留双层 cause chain，从本次 B checkpoint 恢复后应用确定性属性修复，
  API 复验通过，Trace 为 diagnosis→candidate→checkpoint→repair→verify→complete，临时目录清理；
- 真实门只验证 API/property 修复和局部恢复，不声明 solve 或物理审计成功；没有案例晋升 verified
  memory；
- 新增并接受 ADR 0006。剩余生产风险是进程内线程不能硬杀阻塞 Java；可回收进程 Worker 和真实
  卡死 kill 仍留给 M7/M9 前的独立加固。

## 16. M6 P0 加固验收记录

日期：2026-08-21。

- `tests/test_v2_repair.py` 新增合同执行和恢复故障测试：候选空 gates 拒绝、Policy 门禁不可降低、
  precondition/Builder 兼容拒绝、solve/核时预算、成功判据、rollback checkpoint、checkpoint 创建
  失败、commit 失败和 rollback 二级失败；
- Governed RepairCase 现在强制附加 static/runtime gates；Solver executor 必须接收剩余预算、
  checkpoint、成功判据和最终 gates；
- checkpoint/commit/rollback 故障都返回 `RepairResult`；rollback 未确认时要求人工恢复且停止
  后续候选；
- `.venv/bin/python -m pytest tests/test_v2_repair.py -q`：25 passed；M1–M6 联合：116 passed；
  完整 `.venv/bin/python -m pytest -q`：346 passed，1 个既有 Starlette/httpx warning；core 203、
  bearing domain 14、web 13 passed；修改范围 Ruff 通过；
- `.venv/bin/python scripts/run_v2_repair_smoke.py --version 6.2 --cores 1` 再次通过：真实 MPh 1.3.1
  + COMSOL 6.2 产生 `INVALID_PROPERTY`，从 B checkpoint 局部恢复并通过 API gate；Trace 为
  diagnosis→candidate→checkpoint→repair→verify→complete，未运行 solve/audit；
- 新增并接受 [ADR 0007](adr/0007-repair-contract-enforcement-and-recovery-failure.md)。

## 17. M7 验收记录

日期：2026-08-23（针对应力取数和 solver tolerance 的重新严格验收）。

- `tests/test_v2_bearing_domain.py` 33 passed，覆盖严格 schema/几何、ChangeSet、载荷/尺寸/数量/
  相位/四方向零 LLM 路由、A–D 计划、动态延续、4 类 Auditor、manifest discovery、Registry
  启停/卸载和 Kernel 领域中立守卫；
- V2 M1–M7 联合 149 passed；完整非 COMSOL 套件 379 passed，1 个既有 Starlette/httpx
  warning；修改范围 Ruff 通过；
- `.venv/bin/python scripts/run_v2_bearing_gate.py --cores 1 --timeout-seconds 1200` 使用唯一空白模型
  和新目录完成真实 COMSOL 6.2 A–D gate，耗时约 768 秒；10 滚子、45/90×20 mm、7.5×17 mm、
  1.5 mm 总径向游隙、0.3 mm 兜孔间隙、7.5°、+X、1 N；
- 目标步 1 N 返回；实际载荷 `0.999998899 N`，反力合量 `0.999993185 N`，外接触合量
  `1.006473406 N`，稳定力占比 `7.884e-6`；载荷区方向、有限应力/位移、原生 PNG 和 solved MPH
  通过；
- 证据目录 `reports/v2_m7_bearing_evidence/20260823T203213-c9c9b297/` 含 V2 Builder 生成代码、
  约 512 MB solved MPH、configured MPH、PNG、完整摘要、checkpoint 和
  `v2_m7_audit_evidence.json`；每个 material artifact 均记录 SHA-256；
- 内嵌审阅资产 SHA-256 为 `3f8e0d241a4e078f365c90497e6dc3db9be0e78be909b036bfafee684b572062`；
  当前 Builder 输出 SHA-256 为 `a2f95a8b067de9a8c67abf2d44119c21c72169b84ed7c0cc63f13eae5415c77d`，
  与本次真实 gate 执行文件一致；
- 严格结果节点通过 `radial_load/1[N]` 选择目标 1 N，显式绑定 `dset7` /
  solution 1；`solid.mises/1[Pa] = 89433.33087249525 Pa`，
  `solid.disp/1[m] = 3.0172418316622154e-7 m`，原生 PNG 的 dataset、solution、表达式与
  numerical maximum 一致；
- Stationary solver 的真实属性是 `stol`，不是 `rtol`；`sol1`–`sol7` 全部写入/
  读回 `0.001`。旧 `20260822T221835-c97e1b90` 中 `6.2959e-6 Pa` 与原生图矛盾，
  不得再作为应力正确性证据；
- 第一次 gate 因规格漏建径向游隙在静态预检停止，驱动 `BearingSpec` 增加显式总径向游隙合同；
  该失败独立保留且未执行 COMSOL；
- 未晋升 verified memory。-X/±Y 保持可确定性配置但未验证状态；不以历史失败或 mock 降低门禁。

## 18. M7.5 真实 LLM 验收记录

日期：2026-08-23。

- 普通回归使用 fake/replay，覆盖严格 Gateway 合同、JSON Schema、非法输出、取消、中文
  Intake、多轮继承、clarification/invalid/unsupported、RAG 引用、Policy route/capability 复验、
  Prompt injection 拒绝和 exact local PatchSet；
- `tests/test_v2_model_gateway.py` 13 passed；M1–M7.5 联合 162 passed；完整 pytest 392 passed，
  1 个既有 Starlette/httpx warning；Model Gateway/Intake/Planner/Repair/gate 修改范围 Ruff 通过；
- `.venv/bin/python scripts/run_v2_llm_gate.py` 显式调用真实 DeepSeek `deepseek-v4-pro`：
  Intake 1286/483 tokens，Planner 1080/130 tokens，总计 2979 tokens；两个调用均保存版本、
  request id、digest、UTC 时间、usage 和输出来源，API key 未写入证据；
- `.venv/bin/python scripts/run_v2_llm_gate.py --run-comsol --cores 1
  --comsol-timeout-seconds 1200` 完成另一次真实中文需求→Intake→Planner→Builder→
  COMSOL 6.2→Auditor；LLM usage 为 1769 + 1198 = 2967 tokens，Policy 固定 deterministic
  rebuild，RAG 引用保留，全模型 LLM 重写为零；
- E2E 唯一模型 `v2_m7_bearing_953d280afa75434496380beba06e07d4` 的目标 1 N、力平衡、
  `dset7` / solution 1、`solid.mises/1[Pa] = 89433.33087249525 Pa`、
  `solid.disp/1[m] = 3.0172418316622154e-7 m`、原生 PNG、`stol=0.001` 读回和 solved MPH
  全部通过；
- 完整 E2E 证据目录为 `reports/v2_m7_5_llm_evidence/20260823T210207-dceed0e9/`；solved MPH
  SHA-256 为 `ab6207070a6f82ee2005b85184fba47891bbf4bfc03456cb13a2f7823982e6ae`，大型产物不进 Git；
- M9 Definition of Done 新增：外部 LLM 必须 opt-in；真实调用保存脱敏可追溯证据；
  非法结构、未注册 capability、越权 Prompt 和 route 冲突必须在执行前失败；LLM 不能声明
  solve/audit/memory promotion 成功。

## 19. M7.5.1 真实 Kernel 执行补验

日期：2026-08-24。

- 2026-08-23 的 M7.5 COMSOL 证据存在执行旁路：Planner 输出没有经 Kernel/Registry/M5
  Runtime 执行，因此不再计为 Agent E2E 证据；
- 新 gate 由 `AgentKernel(RegistryToolExecutor(snapshot))` 执行已注册
  `bearing.workflow.execute`，证据明确记录 `legacy_gate_subprocess=false`；
- 失败 Observation 定向测试证明进入 M6 Diagnosis/Orchestrator；未确认终止的 timeout
  无可自动修复类型，返回 `user_decision_required`，不重试原 Action；M6 原有预算、
  不可降低门禁和 rollback 套件继续通过；
- +X/1 N 重建链通过：DeepSeek Intake 1769 tokens、Planner 2081 tokens，Kernel plan/action
  完成，四类 Auditor 通过；`solid.mises/1[Pa]` 与原生图 numerical maximum 均为
  `89433.38638405208 Pa`，共用 `dset7` / solution 1；`stol=0.001` 完整读回；
- -Y/10 N 多轮覆盖链使用另一次真实 DeepSeek 调用（Intake 1644 + Planner 2649 =
  4293 tokens），路由为 `parameter_override`，A/B 因相容 B checkpoint 而 skipped，证明没有
  全量 LLM 重写或几何重建；但 C solve 在 1200 s 超时，D 未运行，因此必须
  判为失败，不扩大 verified 支持范围；
- 紧凑 Git 证据见 `docs/v2/evidence/m7-5-1-kernel-e2e-20260824.json`；完整成功/失败
  artifact 分别位于 `reports/v2_m7_5_llm_evidence/20260824T005747-333bcb11/` 和
  `reports/v2_m7_5_llm_evidence/20260824T012153-95cb6a82/`。
