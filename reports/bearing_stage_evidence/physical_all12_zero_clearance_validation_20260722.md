# 12 滚子零游隙参考模型验证（2026-07-22）

## 结论

按“外圈支承 + 内孔 X 向边界载荷 + X 向自由 + Y/Z 弱导向 + 12 滚子自然接触”重建的零游隙参考模型通过了载荷传递和自然载荷区验证。它可作为 Agent 生成同类轴承模型的已验证参考拓扑，但不得冒充已给定实际游隙/过盈的设计级模型。

## 已验证项

- 内孔载荷选择只包含 4 个圆柱面分片（实体 129、130、132、133），面积 `0.0022619428 m²`，与 `pi*inner_diameter*bearing_width` 一致。
- 积分输入载荷 `0.1009998244 N`。
- 外圈固定支承权威反力 `solid.RFx = -0.1009997907 N`，相对平衡误差约 `3.3e-7`，远低于 1% 门槛。
- 内孔 X 向位移约束反力为 `0 N`；保持架固定 X 反力为 `0 N`。
- 12 个滚子弱弹簧 X 向合力约 `1.8e-8 N`，相对 `0.101 N` 可忽略。
- 接触载荷形成有限载荷区：1 号滚子最大，2/12、3/11、4/10 逐级递减，6–8 号基本脱离接触。
- 所有数值探针显式读取最新解集 `dset6`，避免误读 `dset1`。

## 已定位的旧模型错误

旧 `sel_inner_bore_load_surface` 使用宽 Box + `condition='intersects'`，同时选中 4 个内孔圆柱面和 4 个内圈端面。错误面积 `0.0048631788 m²` 导致压力归一化和载荷面都不正确，是旧反力只有约 78% 的核心原因。

## 适用边界

- 本次通过的是 `zeroInitGap=1` 的“零游隙装配参考”。
- 尝试从已平衡解切换到 `zeroInitGap=0` 时，非线性求解仍因相对步长过小而不收敛。
- 因此，如果需要真实游隙、过盈或预紧，必须输入实际数值、重建几何/初始间隙，并重新通过同样的反力和逐滚子载荷门槛。

## 证据

- 求解模型：`runtime_smoke/bearing_physical_all12_strict_bore_k1e4_zig1_20260722/result_packages/actual_area_resume_from_solved_nominal.mph`
- 载荷探针：`runtime_smoke/bearing_physical_all12_strict_bore_k1e4_zig1_20260722/load_probe_solved_mph/load_probe_summary.json`
- 反力探针：`runtime_smoke/bearing_physical_all12_strict_bore_k1e4_zig1_20260722/support_reaction_probe_authoritative_rfx/reaction_probe_summary.json`
- 载荷路径与逐滚子接触：`runtime_smoke/bearing_physical_all12_strict_bore_k1e4_zig1_20260722/physical_load_path_audit.json`
- 0.101 N COMSOL 原生应力图：`runtime_smoke/bearing_physical_all12_strict_bore_k1e4_zig1_20260722/stage_plots/physical_all12_final_0p101n_v2_native_volume.png`
- `zeroInitGap=0` 失败记录：`runtime_smoke/bearing_physical_all12_strict_bore_k1e4_zig0_20260722/direct_3d_bearing_summary.json`
