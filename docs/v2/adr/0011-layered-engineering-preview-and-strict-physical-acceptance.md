# ADR 0011: 分层的工程预览与严格物理验收

- 状态：Accepted
- 日期：2026-08-31

## 背景

V2 原本把力/反力/接触合力平衡、稳定项占比和载荷区方向等严格物理审计作为每次生成结果的唯一验收门。当前产品需求是先交付真实 COMSOL 求解得到、应力量级合理的工程模型；局部力平衡误差不应阻断这类预览结果。

同时，VerifiedCase 和 verified memory 必须继续只接受严格物理证据，不能把“应力看起来合理”当作物理正确性证明。

## 决策

1. 轴承工作流新增两个显式验收模式：
   - `engineering_preview`：默认交付门；
   - `strict_verified`：正式物理验证和记忆晋升门。
2. `engineering_preview` 必须来自本次真实 COMSOL 求解，并同时满足：
   - 几何、选择集和接触绑定审计通过；
   - 目标结果步存在；
   - 应力源为 `solid.mises/1[Pa]`，值为有限正数；
   - 应力落在版本化工程范围内。默认范围为 `1e3..1e9 Pa`，调用方可改用 `expected_pa` 和 `relative_tolerance`；
   - 有绑定相同 dataset/solution 的原生应力图。
3. 力/反力/接触合力平衡、稳定项占比和载荷区方向仍运行严格 Auditor。它们在预览模式中作为可追溯 warning，在 `strict_verified` 中仍为阻断错误。
4. 界面和事件投影用 `engineering_preview_accepted` 表示预览通过；只有严格门可表示 `physical_audit_passed`。
5. 预览结果始终标记 `promotion_eligible=false`，不能晋升 VerifiedCase 或 verified memory。

## 后果

- 真实求解、结构完整且应力量级合理的模型可以作为默认工程预览交付，局部平衡误差不再把整个会话判为失败。
- 调用方需根据用途明确选择验收模式；认证、基准回归和记忆晋升仍使用 `strict_verified`。
- 应力范围宽松但不是无条件通过；NaN、非正值、错误表达式、错误解或缺失原生图仍会失败。

## 验证

- 预览模式在应力合理但严格平衡失败时通过，并保留 strict warning。
- 相同输入在 `strict_verified` 模式下失败。
- 投影不用未选中的 strict 失败覆盖 preview 门，也不把 preview 显示为严格物理通过。
- VerifiedCase 和 memory promotion policy 保持不变。
