# V2 动态扩展系统

## 1. 目标

V2 使用扩展系统承载可动态添加、删除、启用或禁用的能力。Kernel 不通过修改条件分支来认识新的轴承、修复规则或 COMSOL 工作流。

扩展系统需要同时支持：

- Function / Tool；
- MCP Server 与 MCP Tool；
- Skill；
- Hook；
- Repair Rule；
- Deterministic Path；
- Builder、Validator 和 Auditor；
- Memory Adapter 与 Retriever。

## 2. 能力边界

| 类型 | 负责 | 不负责 |
|---|---|---|
| Function | 进程内、类型化、可测试的确定性动作 | 外部服务授权和长工作流说明 |
| MCP | 外部数据和受控动作边界 | 决定完整业务流程 |
| Skill | 教 Agent 何时、按何顺序组合工具 | 提供额外权限或绕过 Policy |
| Hook | 生命周期检查、日志、阻断和上下文注入 | 替代主要业务流程 |
| Repair Rule | 匹配错误并产生受限修复动作 | 无限制重写模型 |
| Deterministic Path | 满足前置条件时执行稳定 DAG | 处理未声明的新拓扑 |
| Builder | 从类型化规格生成领域模型片段 | 自主改变用户需求 |
| Validator/Auditor | 判断合同、运行或物理门槛 | 修改被审计对象 |
| Memory Adapter | 读写和版本化记忆 | 决定记忆是否物理正确 |

## 3. 扩展 Manifest

所有扩展共享基础字段：

```yaml
api_version: comsol-agent/v2alpha1
kind: repair_rule
id: comsol.selection.create_before_use
version: 1.0.0
enabled: true
entrypoint: comsol_agent.v2.repair.rules.selection_order:SelectionOrderRule
description: Reorder component selections so every referenced tag already exists.

compatibility:
  agent_api: ">=2.0,<3"
  comsol: ["6.x"]

permissions:
  filesystem: read
  shell: none
  comsol: model_write
  network: none

priority: 100
config_schema: schemas/selection-order.schema.json
tests:
  - tests/test_selection_order_rule.py
```

必需规则：

- `id` 全局唯一且稳定；
- `version` 使用语义版本；
- `entrypoint` 只允许来自可信安装路径；
- 权限必须显式声明；
- 配置必须通过 schema；
- 兼容性不满足时拒绝加载，而不是带警告继续执行。

## 4. Registry 与生命周期

Registry 提供：

```python
discover(paths) -> list[ExtensionCandidate]
validate(candidate) -> ValidationResult
register(extension) -> Registration
enable(extension_id) -> None
disable(extension_id) -> None
unregister(extension_id) -> None
resolve(kind, capability, context) -> list[Extension]
health(extension_id) -> HealthReport
```

生命周期：

```text
discovered → validated → registered → enabled → active
                  ↓            ↓          ↓
               rejected     disabled   unhealthy
```

加载失败必须隔离到单个扩展。一个非核心扩展不能阻止 Kernel 启动，除非当前 Goal 明确依赖它。

## 5. 冲突与选择

Registry 不允许“最后加载者静默覆盖”。多个扩展匹配同一能力时按以下顺序处理：

1. 硬兼容和权限过滤；
2. 用户或项目显式选择；
3. 前置条件和领域签名；
4. 优先级；
5. 质量与健康状态；
6. 若仍冲突，返回结构化冲突而不是随机选择。

## 6. Function 工具

Function 使用严格输入输出 schema，并声明：

- 是否只读；
- 是否幂等；
- 超时；
- 可重试错误；
- 副作用；
- 权限；
- 结果和错误 schema。

适合的 Function：规格解析、依赖排序、几何关系校验、错误分类、力平衡计算和 artifact 索引。

## 7. MCP

MCP 是 COMSOL 和其他外部能力的首选边界。V2 MCP Client 需要：

- server 发现、能力枚举和健康检查；
- tool schema 缓存与版本；
- 调用超时、取消和权限审批；
- 结构化结果标准化；
- 连接失败与业务失败分离；
- 调用 Trace 和敏感字段过滤。

COMSOL MCP 不直接接收任意 Shell 命令；它暴露受控模型操作。详细工具见 [COMSOL_RUNTIME.md](COMSOL_RUNTIME.md)。

## 8. Skill

Skill 包含工作流说明、参考资料、脚本、模板和测试。建议布局：

```text
skills/build-cylindrical-bearing/
  SKILL.md
  references/
  scripts/
  templates/
  tests/
```

Skill 元数据负责触发，正文负责步骤。Skill 可以调用 Function 或 MCP，但不能自行提升权限。典型 Skill：

- `build-cylindrical-bearing`；
- `diagnose-comsol-api-error`；
- `repair-empty-selection`；
- `run-contact-continuation`；
- `audit-bearing-force-balance`；
- `promote-verified-case`。

## 9. Hooks

V2 事件总线至少提供：

```text
RunStart
GoalPlanned
BeforeRetrieve / AfterRetrieve
BeforeAction / AfterAction
BeforeFileEdit / AfterFileEdit
BeforeSandboxExec / AfterSandboxExec
BeforeComsolStage / AfterComsolStage
BeforeRepair / AfterRepair
BeforePromotion
RunStop / RunEnd
```

Hook 用于日志、策略和机械门禁。它不能隐式修改主要领域状态；任何修改必须返回显式 Patch/Decision 并写入 Trace。

## 10. Repair Rule

Repair Rule 采用“声明式匹配 + 受限 handler + verifier”：

```yaml
kind: repair_rule
id: comsol.result.remove_invalid_looplevel
enabled: true
priority: 90

match:
  error_class: INVALID_PROPERTY
  node_type: PlotGroup3D
  property: looplevel

scope:
  stages: [results]
  max_attempts: 1

action:
  handler: comsol_agent.v2.repair.rules.results:remove_pre_solve_looplevel

verification:
  - validate_property_schema
  - comsol_execute_segment
```

规则必须输出补丁，不直接在不可追踪的位置改写代码。

## 11. Deterministic Path

确定性路径是可注册 DAG：

```yaml
kind: deterministic_path
id: bearing.parameter_override
enabled: true

trigger:
  domain: bearing
  change_types: [load_parameter, material_parameter, solver_parameter]

preconditions:
  - topology_signature_unchanged
  - compatible_verified_baseline_exists

steps:
  - retrieve_verified_baseline
  - apply_parameter_patch
  - validate_spec
  - restore_checkpoint
  - solve_load_continuation
  - audit_physics

rollback:
  checkpoint: configured_model

acceptance:
  - target_load_reached
  - force_balance_passed
  - result_artifacts_present
```

路径的步骤只能引用已注册能力。删除某能力时，Registry 必须报告受影响路径。

## 12. 动态增删与信任

- 声明式规则可以热加载，但必须先通过 schema 和测试夹具；
- Python 扩展需要可信来源和代码审查；
- 运行中的 Goal 固定扩展快照，不受中途热更新影响；
- 删除扩展前检查依赖路径、Skill 和历史 RunManifest；
- 历史记录保存扩展 ID 和版本，不要求扩展永久存在；
- 禁用优先于删除，以便回滚和复现。

## 13. 扩展验收

每种扩展至少验证：

- manifest/schema；
- 注册、启用、禁用和卸载；
- 重复 ID 与版本冲突；
- 权限拒绝；
- handler 异常隔离；
- Trace 完整性；
- 兼容性拒绝；
- 依赖扩展缺失；
- 在无 LLM 条件下的确定性测试。

## 14. M2 实现映射

M2 的领域无关实现位于 `comsol_agent/v2/extensions/`：

- `models.py` 定义 `comsol-agent/v2alpha1` 严格 Manifest、四类显式权限、兼容、扩展版本依赖与
  `(kind, capability)` 能力依赖、候选、
  校验、生命周期、健康、冲突和 Trace 合同；`ExtensionManifest.model_json_schema()` 是规范化
  manifest JSON Schema 来源；
- `interfaces.py` 提供 Function、MCP Server/Tool、Skill、Hook、Repair Rule、Deterministic
  Path、Builder、Validator、Auditor、Memory Adapter 和 Retriever 协议；
- `loader.py` 将无代码执行的 YAML/JSON discovery 与可信 entrypoint import 分离，按 Python
  实际生效顺序检查 `sys.path`/`sys.modules` 及父包来源，导入后复验来源，并对扩展配置执行
  Draft 2020-12 JSON Schema 校验；
- `policy.py` 在 import/注册前硬检查 Agent API、COMSOL 版本和安装权限上限，并在调用时检查
  Action 所需权限；
- `registry.py` 实现注册、启停、健康、卸载、显式依赖、结构化冲突、生命周期 Trace 和异步
  租约式运行快照；注册时拒绝缺失能力，卸载唯一 provider 时报告受影响路径/扩展；逐扩展锁
  串行化生命周期变化，禁用在等待 deactivation 前立即阻止新解析，已有快照关闭前延迟清理并
  拒绝卸载；故障扩展进入 `unhealthy` 而不阻断其他扩展；
- `executor.py` 将固定快照适配到 M1 `ToolExecutor`，对 Function/MCP Tool 的输入输出 schema、
  权限和异常做统一 Observation 标准化。

运行中的 Goal 必须用 `async with registry.snapshot()` 获取一次 `ExtensionSnapshot` 并记录其
`versions`；后续 Registry 热更新只影响新运行，退出上下文时释放租约和延迟清理。直接
`register()` 实例是宿主进程内可信装配；不可信安装必须经过 Loader。
该策略由 [ADR 0002](adr/0002-extension-trust-lifecycle-and-resolution.md) 固化。
