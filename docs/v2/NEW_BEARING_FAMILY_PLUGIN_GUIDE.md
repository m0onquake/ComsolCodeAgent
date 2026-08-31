# V2 新轴承族插件指南

## 1. 目标与不可跨越的边界

新增深沟球、圆锥滚子或其他轴承族时，应增加一个可信领域插件，不得在 Kernel、通用 Runtime、
Repair Orchestrator 或 Web 投影中增加 family 条件分支。Skill 只描述工作流；真实模型动作必须由
Function/MCP、Builder 或 Deterministic Path 执行，物理结论必须来自本次 COMSOL 与版本化 Auditor。

新 family 在真实 A–D 和严格物理审计通过前只能标记为 `candidate`。图片、历史 MPH、fixture、
静态校验或相似案例不能扩大 verified 支持范围。

## 2. 最小插件组成

建议在 `comsol_agent/v2/domains/<family>/` 提供：

```text
models.py                 # 严格 FamilySpec、单位、派生值和版本
changes.py                # ChangeSet 与 topology/build/physics signature
builder.py                # 确定性 A/B Builder
paths.py                  # 参数覆盖和载荷延续 DAG
auditors.py               # geometry/selection/contact/physics
workflow.py               # 固定 capability 的 Function 边界
skill.py                  # 无权限的工作流说明
extensions.py             # 扩展对象工厂
manifests/
  01-builder/manifest.yaml
  02-geometry-auditor/manifest.yaml
  ...
```

至少注册一个 Builder、四类 Auditor、参数覆盖 Path、载荷延续 Path 和一个 Skill。若新 family 有
独立的非收敛策略，应注册 Solver Strategy；不得把它伪装成一般 Repair Rule。

## 3. 实现顺序

1. 定义 `FamilySpec`，保存用户显式值、默认/派生值、单位、provenance、schema 版本和签名。
2. 定义 ChangeSet。载荷、方向和 solver 参数只有在拓扑签名不变时才能复用 B checkpoint；几何、
   数量、相位和接触拓扑变化必须确定性重建。
3. 实现 Builder。输入只能是类型化规格，不接受任意 Python/Java/Shell；输出记录模型摘要和选择。
4. 实现 Geometry、Selection、Contact、Physics Auditor。每个 Auditor 独立返回门禁与证据。
5. 编写 manifest，声明稳定 ID、语义版本、能力、依赖、权限、兼容、优先级和健康检查。
6. 通过可信 Loader/Registry 注册；验证启用、禁用、卸载、冲突和固定快照，不编辑 Kernel registry。
7. 将 workflow 暴露为严格 Function；Planner 只能从 `ExtensionSnapshot` 产生 ID/version/kind/
   capability pin，LLM 输出仍需 Policy 和本地 schema 复验。
8. 增加 spawn-safe backend factory，使生产 COMSOL Client、执行 catalog 和 Auditor 全部在可回收
   子进程内创建；不能把父进程 MPh Client fork 到子进程。

## 4. Manifest 示例

```yaml
api_version: comsol-agent/v2alpha1
kind: builder
id: bearing.tapered-roller.builder
version: 1.0.0
enabled: true
entrypoint: comsol_agent.v2.domains.tapered.extensions:tapered_builder_extension
description: Deterministic 3D tapered-roller bearing builder.
compatibility:
  agent_api: ">=2.0,<3"
  comsol: ["6.x"]
permissions:
  filesystem: write
  shell: none
  comsol: model_write
  network: none
capabilities: [bearing.tapered-roller.build]
priority: 100
quality: 1.0
```

依赖必须写入 manifest。若两个 provider 在硬过滤、显式选择、优先级和质量后仍同分，Registry
必须返回冲突，不能依赖加载顺序。

## 5. 物理 Auditor 最低证据

- 目标载荷步确实返回；
- 实际载荷、支承反力、内外接触合力和稳定项比例；
- 载荷区方向以及与几何/相位一致性；
- 选择实体数量、面积和 pair source/destination；
- 有限应力/位移，保存 expression、unit、dataset、solution 和 source；
- 原生图与 numerical maximum 使用同一 dataset/solution/expression；
- configured checkpoint、solved MPH、审计 JSON 和每个 material artifact 的 SHA-256；
- Agent、COMSOL、MPh、Builder、Auditor、扩展快照和输入版本。

阈值属于版本化物理合同。修复不能放宽阈值、忽略异常或用非目标参数步替代。

## 6. 必须通过的测试与真实门

普通回归（不调用外部 LLM）至少覆盖：schema、非法几何、ChangeSet、零自由全模型重写路由、
manifest discovery、启停/卸载/冲突、权限拒绝、固定 pin、checkpoint 兼容和 Auditor 负例。

真实门按风险逐层运行：

1. lifecycle；
2. Builder A/B 与选择/接触审计；
3. 基准载荷 C/D；
4. 同拓扑高载荷 checkpoint 复用；
5. 相位、方向、合法尺寸和数量变化；
6. 非收敛与已知 API 错误的有限修复；
7. 显式 opt-in 的自然语言→Planner→Kernel→Registry→进程 Worker→COMSOL→严格 Auditor；
8. 在 C 阶段阻塞时的真实进程强取消。

每次真实门使用唯一模型名和隔离目录。失败同样落盘且不得晋升 memory。新 family 只有上述适用门
全部通过、文档与兼容矩阵更新后才能从 `candidate` 改为 `verified`。

## 7. 发布与移除

发布时记录扩展 ID/version、支持的 COMSOL/MPh、已验证参数 envelope、证据哈希和已知失败签名。
回滚优先禁用扩展；运行中的固定快照自然结束后再卸载。删除前检查 Deterministic Path、Skill、
历史 RunManifest 和 checkpoint 依赖。旧记录保留 provenance，不要求旧扩展仍可执行。
