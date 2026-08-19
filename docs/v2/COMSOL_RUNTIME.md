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

建议能力：

```text
comsol.health
comsol.create_scratch_model
comsol.execute_segment
comsol.run_geometry
comsol.list_features
comsol.inspect_feature
comsol.inspect_selection
comsol.inspect_pairs
comsol.run_mesh
comsol.configure_study
comsol.solve_stage
comsol.evaluate
comsol.export_plot
comsol.save_checkpoint
comsol.restore_checkpoint
comsol.close_model
```

每个工具使用类型化参数，声明只读/写入、幂等性、超时和所需模型状态。

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

| 阶段 | 完成条件 | 检查点 |
|---|---|---|
| A Parameters/Geometry | 参数、基本几何可运行 | `checkpoint_A_geometry.mph` |
| B Topology/Assembly | 滚子、保持架、分割和装配完成 | `checkpoint_B_assembly.mph` |
| C Selections/Physics | 选择集、材料、约束、载荷和接触有效 | `checkpoint_C_physics.mph` |
| D Mesh/Study/Results | 网格、研究和结果节点有效 | `checkpoint_D_mesh_study.mph` |
| Initialization | 接触初始化收敛且状态可审计 | `checkpoint_initialized.mph` |
| Solve | 目标载荷步收敛 | `checkpoint_solved.mph` |

检查点绑定 EngineeringSpec、代码、扩展集合和 COMSOL 版本哈希。任一不匹配则拒绝恢复。

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
- 并发运行使用独立 COMSOL 会话或显式队列。

## 13. Runtime 验收

- 每个工具 schema 可验证；
- 嵌套异常完整上浮；
- 检查点兼容性可拒绝错误恢复；
- 取消/超时释放模型锁；
- 已知错误可从最近检查点局部复验；
- 同错重复受到限制；
- API 成功、Solve 成功和 Audit 成功状态分离；
- Trace 能重建一次运行的关键动作。
