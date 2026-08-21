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
  丢失降级为 `needs_revalidation`、RepairCase 错误签名精确匹配和 invalidated 案例拦截；
- Context Pack 验证一个主案例、最多两个辅助案例、角色/provenance 和 artifact 引用，不内联历史
  基线代码；RetrievalEvaluator 使用采用后的执行、严格审计和修复结果，并回写历史采用成功率；
- `.venv/bin/python -m pytest tests/test_v2_memory.py -q`：16 passed；
- `.venv/bin/python -m pytest tests/test_v2_kernel.py tests/test_v2_extensions.py
  tests/test_v2_code_tools.py tests/test_v2_memory.py -q`：71 passed；
- `.venv/bin/python -m pytest -q`：301 passed，1 个既有 Starlette/httpx 弃用 warning；
- `.venv/bin/ruff check comsol_agent/v2 tests/test_v2_memory.py scripts/migrate_v2_memory.py`：通过；
  全仓 `--statistics` 仍报告 3136 个 M3 已记录的旧问题，M4 修改范围没有新增问题；
- M4 不调用 COMSOL，真实求解和物理回归不适用；测试中的严格审计证据只验证 promotion policy，
  没有将 fixture 或历史 artifact 写入持久 verified memory；
- 新增并接受 ADR 0004；实现提交为 `99b38d662b574c61aee71bc3bc7b8431af0077da`。
