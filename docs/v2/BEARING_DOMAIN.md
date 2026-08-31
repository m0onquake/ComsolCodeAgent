# V2 轴承领域插件

## 1. 边界与支持范围

M7 在 `comsol_agent/v2/domains/bearing/` 提供圆柱滚子轴承领域插件。Kernel、Runtime 和 Repair
包不导入该插件；能力由 9 个 manifest 经 Registry 动态发现、校验、启停和固定快照。

当前类型化范围是 3D 单列圆柱滚子轴承、Boolean 兜孔保持架、内外两组全局滚道接触、内孔径向
载荷和外圈支承。`BearingSpec` 显式保存尺寸、滚子数量、总径向游隙、兜孔间隙、相位、方向、
载荷、网格、求解容差、schema 和 provenance。几何合同允许零游隙和已验证的正游隙配置；不把
静态相似或历史结果当作物理正确。

本次真实严格验收验证了 10 滚子、45/90 mm 内外径、20 mm 宽度、7.5×17 mm 滚子、1.5 mm
总径向游隙、0.3 mm 兜孔间隙、7.5° 相位、+X、1 N。四方向都可由确定性代码配置且不会触发
全量 LLM 重写；但 -X、±Y 尚未由本次 M7 gate 晋升为 verified 参数签名，必须继续经过真实
求解和相同严格审计。

## 2. 最小修改路由

`classify_changes()` 产生版本化 `BearingChangeSet`：

- 载荷、方向、网格和求解参数使用 `bearing.parameter-override`，恢复相容 B 检查点后只改类型化
  参数或对应物理/求解器节点；`solver_relative_tolerance` 映射为 COMSOL Stationary
  feature 的 `stol`，必须写入后读回，不冒充 model parameter；
- 尺寸、径向/兜孔游隙、滚子数量和相位会影响已构建几何、重复实体或选择定位，因此使用已注册
  `bearing.cylindrical-roller.builder` 确定性重建；
- 未知 family 或拓扑返回 `unsupported_topology`；
- 上述支持变更的 `requires_llm` 均为 false。

参数路径和重建路径都必须重新求解并运行严格物理审计。默认工程预览可按第 4 节的
近似应力门交付；参数覆盖不等于复用旧结果。

## 3. A–D Builder 与延续

- A：严格规格和几何关系，创建内外圈、滚子和保持架；
- B：命名选择、两组全局接触、材料/物理和局部网格，保存 configured checkpoint；
- C：按方向/相位生成动态载荷序列，分块继承收敛解并保留最近 B/收敛检查点；
- D：导出原生图、solved MPH 和审计 JSON。

Builder 的公开输入只有 `BearingSpec`。执行 handler 只能运行内部固定的、经过审查的 V1
确定性资产，不接受用户源代码，也不增加任意 Java/Python/Shell 工具。

## 4. Auditor

五类 Auditor 独立注册：

- Geometry：滚道/滚子/游隙闭合、环厚、周向不重叠；
- Selection：所有载荷、支承、滚道、聚合滚子和逐滚子选择非空；
- Contact：两组全局 pair 的命名 source/destination 和实体非空；
- Physics：目标步、实际载荷、反力、外接触合力、稳定项、载荷区方向、有限应力/位移、原生图
  和 solved MPH。数值应力必须显式使用 `solid.mises/1[Pa]`，位移必须使用
  `solid.disp/1[m]`；报告保存 expression、unit、dataset、solution number 和 source。原生图必须绑定
  同一 dataset/solution/base expression，且其记录的 numerical maximum 与数值结果一致。
- Engineering Preview：目标步、`solid.mises/1[Pa]` 有限正值、版本化近似应力
  范围和相同 dataset/solution 的原生应力图。默认范围为 `1e3..1e9 Pa`，也可传入
  期望应力与相对容差。严格 Physics 失败在预览中保留为 warning。

严格物理阈值是版本化合同，修复路径不能暗中降低。预览通过始终为
`promotion_eligible=false`；COMSOL API 成功、solve 成功、preview 成功和 strict audit 成功
保持分离。见 [ADR 0011](adr/0011-layered-engineering-preview-and-strict-physical-acceptance.md)。

## 5. Skill、权限和证据

`bearing.cylindrical-roller.skill` 只描述规格解析、最小路由、A–D 顺序、失败停止和晋升门槛；它
不授予 COMSOL 权限。执行权限来自 MCP/manifest/Action/Policy 的交集。

真实 gate：

```bash
.venv/bin/python scripts/run_v2_bearing_gate.py --cores 1 --timeout-seconds 1200
```

每次运行创建唯一模型和证据目录，保存 configured/solved MPH、原生 PNG、严格摘要、checkpoint、
SHA-256 和 V2 四类审计结果。失败运行同样保留结构化证据，且不会晋升 verified memory。

2026-08-23 的重跑使用 `dset7` / solution 1 / `radial_load=1 N`，得到最大等效应力
`89433.33087249525 Pa` 和最大位移 `3.0172418316622154e-7 m`；原生图绑定同一解。
2026-08-22 报告中 `6.2959e-6 Pa` 的通用数值评估与原生图矛盾，已被标记为无效应力
证据，不再支持 M7 物理结论。
