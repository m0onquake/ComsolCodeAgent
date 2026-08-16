# 通用建模能力扩展开发计划

Last updated: 2026-07-14

当前开发分支：`codex/general-modeling-expansion-p11-mvp`，基线分支：`codex/segmented-3d-generation`

## 目标

把本项目从“轴承建模能力很强的 COMSOL Agent”扩展为“面向多类工程对象的通用 COMSOL 建模 Agent”。轴承仍然作为高质量标杆案例保留，但系统入口、需求拆解、模板检索、生成代码、质量门和结果打包都不能再假定用户一定在做轴承。

首批非轴承模型族：

- 偏心轴 / 转轴 / 转子：结构静力、转动载荷、偏心质量、模态/频响、应力与位移输出。
- 齿轮 / 齿轮副：齿面接触、传动扭矩、啮合区局部网格、接触压力与 von Mises 应力输出。
- 电路板 / PCB：电流、焦耳热、热传导、器件热源、铜层/基板材料、多物理场温升输出。

后续可扩展到支架、散热器、管路、壳体、流道、声学腔体、电磁执行器等模型。

## 设计原则

1. 需求拆解先通用、再领域细化：先抽取几何、物理场、材料、边界、载荷、研究类型、输出、验证要求，再判断模型族。
2. 模板优先但不模板锁死：匹配模板时使用模板；不匹配时进入受控 generated-code 路径。
3. 模型族是插件式注册项：偏心轴、齿轮、PCB 和轴承都应是 registry 中的 `ModelFamilySpec`，而不是散落在 prompt 和工具里的特判。
4. 质量门分两层：通用 COMSOL 代码安全/结构检查 + 模型族专属物理检查。
5. 结果包通用化：从 `bearing_contact_package` 演进到 `modeling_result_package`，其中可附加轴承、齿轮、PCB 等领域指标。
6. 每个新增模型族必须有三件套：需求规划器、最小可运行模板/生成案例、离线单测和可选真实 COMSOL smoke。

## 当前可复用基础

- `RequirementState` 已开始把跨轮对话需求槽位注入 `simulation_plan_generated_code`。
- `simulation_plan_generated_code` 已具备通用 generated-code planning、模板检索、文档检索、缺失决策和受控 prompt block。
- `comsol_agent/simulation/skills.py` 已有 `SimulationSkill` 和内置模板注册机制。
- 轴承路径已有较完整的 planner、template、quality gate、demo script、artifact reader/report 经验，可以抽象为通用模式。
- `comsol_agent/simulation/bearing_3d.py` 已把一部分原本 demo-script 内的质量门和分段生成 contract 模块化，可作为后续模型族 quality contract 的样板。

## P11-MVP 合并范围

目标：本轮不追求完整多物理场建模和真实 COMSOL starter template，而是先提供一个模型族无关的规划入口，解决“非轴承请求被误路由成轴承模板”的核心问题。

MVP 包含：

1. 新增独立 `ModelFamilySpec` registry，覆盖 `bearing_contact`、`eccentric_shaft`、`gear_pair`、`pcb_thermal_electric`、`general`。
2. 新增 `simulation_plan_modeling_request`，输出稳定 JSON 契约：`model_family`、`domain`、`ready_to_generate`、`missing_decisions`、`follow_up_questions`、`template_policy`、`recommended_workflow`、`quality_contract`、`next_tool_chain`。
3. 复用 `simulation_plan_generated_code` 的模板检索、API 文档检索和 generated-code fallback，不重写底层生成链路。
4. 明确区分自然语言需求槽位和可执行模板参数：`RequirementState.to_modeling_request()` 保留意图槽位，但只把可执行/可验证参数放入 planner 的 `known_params`。
5. 保留现有轴承能力：`simulation_plan_bearing_contact`、`simulation_export_bearing_contact_package` 和 3D bearing selection/quality gate 继续存在；通用 planner 对 `bearing_contact` 只做包容式路由。
6. 反例测试覆盖偏心轴、PCB、齿轮副、轴承正例和信息不足 follow-up，确保结构域非轴承请求不会推荐 `bearing_contact_pair_seed`。

MVP 不包含：

- PCB 真实纯热 starter template。
- 偏心轴静力 starter template。
- 齿轮接触 starter template。
- 通用 `simulation_export_model_package`。
- 真实 COMSOL 多物理场 smoke。

验收命令：

```bash
python3 -m compileall -q comsol_agent tests scripts
python3 -m pytest -q tests/test_core.py -k "modeling_request or model_family"
```

## P12 PCB 工程级纯热 starter template MVP

目标：在 P11 通用 planner 和模型族 registry 的基础上，给 `pcb_thermal_electric` 增加一个可信的纯热起步模板。该模板仍然是 starter template，不要求本轮真实 COMSOL smoke，也不加入 Electric Currents/Joule Heating；但物理内容不能退化为“一块板 + 一个热源”的玩具示例。

P12 包含：

1. 新增内置模板 `pcb_thermal_plate_seed`，domain 为 `thermal`。
2. 几何包含 FR4 基板、上下等效铜层、两个芯片/封装热源区域。
3. 物理包含 Heat Transfer in Solids、芯片体热源、外表面/底面对流散热、stationary study。
4. 参数包含 `board_length`、`board_width`、`board_thickness`、`copper_thickness`、`chip1_power`、`chip2_power`、`chip_size`、`chip_spacing`、`T_ambient`、`convection_h`、`k_fr4`、`k_copper`、`k_chip`、`rho_fr4`、`Cp_fr4`，并使用单位化字符串。
5. 输出包含温度云图、最高温度和芯片/热点温度指标。
6. `pcb_thermal_electric` 的 `starter_templates` 指向 `pcb_thermal_plate_seed`，通用 planner 对 PCB 热请求可推荐或允许该模板，并继续拒绝无关轴承模板。

P12 不包含：

- Electric Currents。
- Joule Heating 电热耦合。
- 详细 PCB 叠层、过孔、铜走线网络或器件封装热阻网络。
- 真实 COMSOL smoke。真实求解和边界/域 ID 复核放入后续阶段。

## P12.1-P12.3 真实 COMSOL smoke 进展

目标：把 P12 `pcb_thermal_plate_seed` 从离线可验证推进到真实 COMSOL 可执行、可审计、可求解的工程级纯热 smoke，同时不降低 FR4、上下铜层、两个芯片热源、对流散热、stationary study 和温度输出这些工程内容。

状态：

- P12.1 setup smoke：已完成。新增 `scripts/run_pcb_thermal_template_smoke.py`，支持 `--archive-path`、`--artifact-dir`、`--model-name`、`--cores`、`--skip-solve`、`--keep-model`、`--print-summary`，并额外提供 `--skip-comsol` 供离线/CI mock 路径测试。
- P12.2 选择绑定修复：已完成。`pcb_thermal_plate_seed` 保留完整工程内容，并从硬编码域 ID 绑定升级为 runtime 可审计的 named Box/Union selections：FR4、上下铜层、两个芯片热源、底部/侧面/芯片顶部对流边界；`maxop1` component Maximum coupling 已显式创建。
- P12.3 stationary solve smoke：已完成。真实 COMSOL 可创建模型、执行模板、通过结构审计、运行 stationary solve、评估温度并导出温度 PNG。

真实 smoke 命令：

```bash
.venv/bin/python scripts/run_pcb_thermal_template_smoke.py \
  --archive-path runtime_smoke/pcb_thermal_real.sqlite3 \
  --artifact-dir runtime_smoke/pcb_thermal_real \
  --model-name pcb_thermal_smoke \
  --cores 1 \
  --print-summary
```

2026-07-06 验证结果：

- Setup：成功，`simulation_run_template(... validate_first=True)` 执行通过。
- Runtime audit：成功，发现 component=1、geometry=1、geometry features=6、materials=3、Heat Transfer physics=1、physics features=13、mesh=1、study=1、result plot groups=1、numerical nodes=2、selections=10。
- Solve：成功，stationary solve 耗时约 `133.3s`。
- 温度评估：`T` 成功，最高约 `428.489 K`；`maxop1(T)` 成功，最高约 `428.497 K`。
- Plot：成功，`runtime_smoke/pcb_thermal_real/pcb_temperature.png`；MPh 默认 image export 提示 `exports/image` 节点不存在后，脚本使用 Java `Image2D` fallback 导出。
- Artifacts：`runtime_smoke/pcb_thermal_real/summary.json`、`runtime_smoke/pcb_thermal_real/report.md`、`runtime_smoke/pcb_thermal_real/manifest.json`、`runtime_smoke/pcb_thermal_real/pcb_thermal_smoke.mph`。

若后续真实求解再次失败，优先修复点按阶段定位：

- `template_setup` 失败：优先检查 Heat Transfer interface/feature tag、material property API、Box/Union selection API。
- `runtime_audit` 失败：优先检查 named selection 是否绑定到实体，以及 FR4/铜层/芯片/对流边界选择数量。
- `solve` 失败：优先检查薄铜层网格、芯片热源单位、对流边界是否过宽或内部边界被选中。
- `evaluate_temperature` 或 `plot_temperature` 失败：优先检查 `maxop1` coupling、result numerical 表达式和 Java image export fallback。

验收命令：

```bash
python3 -m compileall -q comsol_agent tests scripts
python3 -m pytest -q tests/test_core.py -k "pcb_thermal or modeling_request or model_family"
```

## P12 轴承族自动建模补强进展

目标：让轴承请求先进入独立 bearing-family registry，按真实拓扑、参数槽位和接触策略选择模板/生成链路，并避免把圆柱滚子、圆锥滚子、推力轴承等需求误换成深沟球或 2D smoke。

状态：

- 已新增 `BearingFamilySpec` registry，覆盖深沟球、角接触球、圆柱滚子、圆锥滚子、滚针、推力和 general bearing。
- 已新增 `simulation_plan_bearing_modeling_request`，输出稳定 JSON，并把自然语言 intent 与 COMSOL 可执行参数分离。
- 圆柱滚子 planner 对“12 滚子高载荷 COMSOL 原生应力图”推荐 `legacy_raceway_highload_direct`，summary 顶层写入 `requested_stage_image`，便于 agent 直接选对求解阶段图片。
- 2026-07-07 真实 COMSOL 6.2 高载荷 visual stage 已跑通：max von Mises `3.1717319e6 Pa`、contact-pressure estimate `1.953125e6 Pa`、max displacement `3.361115e-3 m`，原生 Volume PNG 质量门通过。
- 2026-07-07 新增 guided BoundaryLoad 诊断模式：`all_raceway_guided_probe_1n` 和 `all_raceway_guided_low_load_transfer`。两者均能完成 all-12-roller raceway displacement-preload native plots，但在切换到 inner-bore `BoundaryLoad` 阶段失败/被中断；summary 明确记录 `weak_inner_guidance_active`，不得算作最终设计级收敛。
- 2026-07-07 新增 `all_raceway_continuous_boundary_load`：从第一阶段就激活 inner-bore `BoundaryLoad`，用小载荷+位移预紧闭合接触，再 ramp 到高载荷；summary 通过 `requested_stage_image` 拒绝把低预紧 native 图冒充高载荷结果，并标出 retained displacement preload / weak guidance。真实 COMSOL 运行已保存失败证据：`continuous_boundary_load_contact_closure_1n` 初始参数步不收敛，failed MPH 在 `runtime_smoke/bearing_family_p12_continuous_boundary_load/bearing3d_continuous_boundary_load/failed_3d_contact_model.mph`。
- 2026-07-07 新增 `all_raceway_split_control_boundary_load` 作为下一条诊断路径：BoundaryLoad 仍在 inner bore，位移闭合控制改绑到 `sel_inner_raceway_contact`，summary 记录 `displacement_preload_selection`，避免同一 bore 边界强位移+载荷的初始步冲突。真实 COMSOL 运行仍在 `split_control_boundary_load_contact_closure_0p1n` 初始参数步失败，failed MPH 在 `runtime_smoke/bearing_family_p12_split_control_boundary_load/bearing3d_split_control_boundary_load/failed_3d_contact_model.mph`；相对误差较同面控制下降但仍未收敛。
- 2026-07-07 新增 `all_raceway_high_preload_reaction_equivalent`：沿用已知可收敛的全 12 滚子位移预紧路径，在高预紧阶段创建 `intop_displacement_reaction_probe` 并逐个探测反力表达式；summary 只有在候选表达式真实 evaluate 成功时才写等效载荷，否则记录候选失败，不允许猜。
- 2026-07-07 真实运行 `all_raceway_high_preload_reaction_equivalent` 并 rerun：高预紧 raceway stage 收敛并导出原生 Volume PNG，max von Mises `9283.9437 Pa`、inner-ring max `10590.748 Pa`、max displacement `2.3097057e-4 m`，但仍是 `x10^3 Pa` 位移预紧诊断图，不是 MPa 级高载荷图。反力 probe setup 显示 integration coupling、`opname`、selection 绑定均成功，但 `intop_displacement_reaction_probe(...)` 在 `mph.evaluate` 和 Java `EvalGlobal/getReal()` 中仍为 unknown operator，因此等效载荷未验证。
- 2026-07-07 新增并真实运行 `load_side_group_boundary_load`：保持 inner-bore `BoundaryLoad` 从第一阶段激活，按载荷侧 3 滚子、6 滚子、全 12 滚子逐步启用 contact。带 raceway displacement closure 的版本仍在第一阶段失败；free-closure 版本跑通 3 滚子 0.1 N bootstrap，并导出原生 Volume PNG，max von Mises `6.526523e6 Pa`、inner-ring max `1.1007336e7 Pa`、max displacement `2.060695e-3 m`，但该阶段有 temporary active-roller fixation 和 weak guidance，且后续释放/50 N ramp 尚未收敛，不能作为最终高载荷 12 滚子结果。
- 2026-07-13 新增 stage evidence matrix：`python3 scripts/run_agent_3d_bearing_full_demo.py --stage-evidence-matrix --stage-evidence-root runtime_smoke --stage-evidence-output-dir reports/bearing_stage_evidence` 会扫描 `runtime_smoke/**/direct_3d_bearing_summary.json`，输出 `reports/bearing_stage_evidence/bearing_stage_evidence_matrix.json` 和 `.md`，逐 stage 汇总 solve、native PNG、BoundaryLoad/BodyLoad、active rollers、cage contact、weak guidance、temporary spring、reaction、basic physical plausibility 和 production_ready。当前矩阵扫描 `115` 个 summary、`267` 个 stage row，显示 `production_ready_count=0`、`reaction_verified_stage_count=0`、`converged_native_stage_count=185`，因此 agent 必须明确说明 design-grade BoundaryLoad/cage 和 verified reaction 尚未完成。矩阵现在还会索引 `runtime_smoke/**/reaction_probe_summary.json` 的 saved-MPH 反力复探报告；当前 `saved_reaction_probe_report_count=1`、`saved_reaction_probe_verified_count=0`。highest-trust selector 会跳过 stress/displacement 数值爆炸的 converged native stage；2026-07-14 又新增跨 stage stress-plateau gate，将 `0.101 N` 到 fine `0.2 N` 的 3-roller BoundaryLoad single-solve rows 标为 `boundaryload_sequence_stress_plateau=true`、`physical_plausibility_success=false`，因为 max von Mises 固定而 displacement 增长约 `2.97x`。同日 matrix/summary contract 增加 per-roller max-stress probe 和 active-roller load-distribution gate：新 staged solve 会记录 `per_roller_probe_results` 与 `active_roller_load_distribution`，matrix 暴露 `active_roller_nonzero_probe_ratio`、`active_roller_zero_stress_rollers` 和 `active_roller_load_distribution_success`；BoundaryLoad rows 必须有 active rollers 的 `maxop_roller_i(solid.mises)` 成功且非零结果才可通过 physical plausibility。历史缺 probe 的 BoundaryLoad rows明确降级。真实 `0.101 N` probe-gate rerun 证明 12 个 roller probes 均可 evaluate，但 active rollers 中仅 `roller_2/12` 非零、`roller_1` 近零，因此该 stage 被 active-roller distribution gate 和 stress-plateau gate 双重拒绝，仍是诊断而非物理验收。matrix 新增 `boundaryload_distribution_diagnostics` 聚合：`84` 个 BoundaryLoad rows 中 `83` 个历史 rows 缺 per-roller probe，`17` 个 rows 为 stress plateau，唯一完整 probe 的 zero-carry row 是 `0.101 N` probe-gate，`zero_carry_rollers={"roller_1": 1}`；configured-MPH diagnostic 进一步显示 `roller_1` body selection count `5`、inner/outer contact active、cage contact inactive、weak foundation active、fixed stabilization inactive，因此下一轮应先查 `roller_1` 的接触几何、初始间隙/法向、几何角度/载荷方向映射和 weak-foundation dominance，再推进 `0.5 N/1 N`。reaction 计数还要求候选反力为非零，历史 `0.0 N` 成功 evaluate 不算 verified reaction。
- 2026-07-14 configured-MPH contact-pair endpoint audit 进一步缩小 `roller_1` zero-carry 根因范围：`0.101 N` probe-gate configured MPH 中，`sel_roller_1_body` 绑定到 `5` 个实体，`contact_roller_1_inner` 和 `contact_roller_1_outer` 均 active，`contact_roller_1_cage` inactive，weak foundation active，fixed stabilization inactive；`cp_roller_1_inner_raceway` 的 source/destination 为 `sel_roller_1_inner_contact -> sel_inner_raceway_1_contact`，实体计数 `2 -> 2`，`cp_roller_1_outer_raceway` 为 `sel_roller_1_outer_contact -> sel_outer_raceway_1_contact`，实体计数 `2 -> 2`。刷新后的 no-solve diagnostic 还读取到 `sel_roller_1_body` Box bounds `21.500..32.500 mm` / `-5.500..5.500 mm`，中心 `(27.0 mm, 0.0 mm)`，roller angle `0 deg`，与 `load_inner_bore` 的 `+X` BoundaryLoad 方向角偏差 `0 deg`；inner patch box center 为 `23.0 mm`、outer patch box center 为 `31.0 mm`，相对 `27.0 mm` roller center 的径向偏移为 `-4.0 mm` / `+4.0 mm`，gross patch radial placement 也正确。matrix 还确认 `roller_1` 与非零 active rollers `2/12` 的 contact feature settings 一致：`pn_penalty=5e-5*E_steel`、`useRelaxation=Always`、`irlx=0.12`、`tolcontact=3[um]`、`zeroInitGap=0`。因此当前证据不支持“roller_1 缺 body selection、contact activation、contact pair endpoint、fixed stabilization、gross load-angle mapping、gross patch placement 或静态 contact feature setting 不一致”这些解释；下一步应优先做 solved contact status、初始间隙/法向、weak guidance/foundation 或 active-roller spring 主导性的诊断。
- 2026-07-14 saved-MPH solved contact probe 新增 `--probe-contact-mph` 路径并真实运行在 `0.101 N` probe-gate result-package MPH 上：不重新求解，评估 rollers `1/2/12` 的 roller-side source 与 raceway-side destination contact selections 的 `MaxSurface(solid.mises/solid.disp)`、traction `IntSurface` 候选，以及 `solid.Tn_cp_roller_i_inner_raceway` / `solid.Tn_cp_roller_i_outer_raceway` 等 contact-pair status candidates，报告保存在 `runtime_smoke/bearing_family_p12_boundaryload_probe_gate/bearing3d_load_side_boundaryload_single_solve_0p101_probe_gate/contact_probe_solved_mph/contact_probe_summary.json` / `.md`，并被 stage evidence matrix 索引。最新 matrix 刷新为 `117` 个 summary、`269` 个 stage row、`production_ready_count=0`、`reaction_verified_stage_count=0`、`saved_contact_probe_report_count=3`。probe-gate 报告包含 `972` 个候选、`144` 个成功 evaluate、`90` 个有限非零，其中 `912` 个是 contact-status/pair-variable probes，并显式分类出 `36` 个 `gap_cp_*` 的 `infinite_result`；报告新增 `contact_variable_discovery`，把 generic `solid.Tn/solid.p` 与 pair-specific `solid.Tn_cp_roller_i_*` 拆开，避免把 raceway surface stress 误判为接触对传力。关键线索是 `roller_1` 的 `sel_roller_1_inner_contact` 与 `sel_roller_1_outer_contact` source 侧候选全为零，而对应 raceway destination 侧 generic `solid.Tn/solid.p` 可非零；但 `roller_1` 的 pair-specific `Tn` 仍为零，`Tn.pair_specific_finite_nonzero_count=0`，相邻非零 active rollers `2/12` 的该计数均为 `4`。最新 `pair_enforcement_diagnostic` 还确认 solved-MPH audit 能抓到 6 个目标 raceway Contact Pair 和 12 个 rollers `1/2/12` 相关 Contact features；`roller_1` 的 source/destination 仍为 `sel_roller_1_*_contact -> sel_*_raceway_1_contact` 且实体计数 `2 -> 2`，Contact feature active，`pn_penalty=5e-5*E_steel`、`useRelaxation=Always`、`irlx=0.12`、`tolcontact=3[um]`、`zeroInitGap=0` 与非零 active rollers `2/12` 匹配。新增 normal orientation probe 对每个 source/destination selection 积分 `1`、`nx`、`ny`、`nz` 和滚子径向法向投影；`roller_1` inner/outer source-destination 径向法向均为相反符号，和非零 active rollers `2/12` 一致。随后新增真实单变量 `load_side_group_boundary_load_single_solve_0p101_roller1_pair_swap`：只交换 `roller_1` inner/outer raceway Contact Pair source/destination，求解和 native PNG 导出成功，但 active distribution 仍失败，`roller_1` maxop stress 仅 `1.1406713e-05 Pa`，saved-MPH replay 中 `roller_1 Tn.pair_specific_finite_nonzero_count=0`，而 `roller_2/12` 均为 `4`；交换端点只消除了 source/destination imbalance flag，没有恢复 pair-specific load transfer。随后又新增真实单变量 `load_side_group_boundary_load_single_solve_0p101_active_spring1e9`：保持同一 `0.101 N` fresh single-solve ramp，只把 `active_roller_stabilization_k` 从 `1e10[N/m^3]` 降到 `1e9[N/m^3]`；求解和 native PNG 导出成功，但 active distribution 仍失败，`roller_1=0.0 Pa`、`roller_2≈7.06e4 Pa`、`roller_12≈7.42e4 Pa`，saved-MPH replay 仍显示 `roller_1 Tn.pair_specific_finite_nonzero_count=0`、`roller_2/12=4`。因此下一步优先查 contact gap active state、接触 enforcement/stabilization 具体激活或 geometry-level gap closure，而不是继续重复静态 selection/feature 配置、单纯翻转 source/destination，或只做十倍 active-spring stiffness 调整。该证据仍是 diagnostic，不是 verified load closure 或 production-ready BoundaryLoad 结果。
- 2026-07-14 继续增强 saved-MPH contact probe：报告新增 `geometry_moments_by_roller`，对 contact selections 积分 `1/x/y/z` 和滚子径向坐标，作为 raceway patch 几何/间隙 proxy。对 `0.101 N` probe-gate result-package MPH 的刷新显示，`roller_1` 的 inner/outer source-destination 径向差均约 `9.811 mm`，而非零承载的 `roller_2/12` 分别约 `6.006 mm` inner 和 `2.247 mm` outer；这提示 Box/Intersection raceway patch 在 `0 deg` 载荷滚子处可能选中了整个相交边界实体，而不是局部 contact patch。随后新增真实单变量 `load_side_group_boundary_load_single_solve_0p101_full_raceway_destination`：仅把 active rollers `12/1/2` 的六个 roller/raceway Contact Pair destination 改为全 `sel_inner_raceway_contact` / `sel_outer_raceway_contact`，其他载荷、spring、weak guidance、penalty 和 fresh single-solve ramp 保持不变。真实 COMSOL 运行保存在 `runtime_smoke/bearing_family_p12_boundaryload_destination/bearing3d_load_side_boundaryload_0p101_full_raceway_destination`，未导出 native PNG，summary 记录 `Solve failed: java.lang.NullPointerException`，physical validation 正确拒绝；configured MPH 和 no-solve diagnostic 已保存，确认 full-raceway destination overrides 生效。因此“扩大 destination 到整条 raceway”不是可直接收敛的 production 修复；下一步应优先做真实分割/局部 raceway contact surface 或局部 gap/interference 诊断。最新 stage evidence matrix 刷新为 `118` 个 summary、`270` 个 stage row、`production_ready_count=0`、`reaction_verified_stage_count=0`、`converged_native_stage_count=187`。
- 2026-07-14 继续运行全局几何干涉单变量诊断：在既有 `load_side_group_boundary_load_single_solve_0p101` fresh ramp 上只增加 `--contact-interference '20[um]'`，其他 active rollers、BoundaryLoad、weak guidance、weak roller foundation、active-roller spring 和 contact settings 不变。真实 COMSOL run 保存在 `runtime_smoke/bearing_family_p12_boundaryload_interference/bearing3d_load_side_boundaryload_0p101_interference20um`，初始参数即失败，solver error 为 `找不到初始参数的解` / `不收敛，相对步长太小`，无 native PNG，physical gate 拒绝；`failed_3d_contact_model.mph`、configured MPH、summary 和 no-solve diagnostic 均已保存。新的 no-solve diagnostic `parameter_audit` 确认 `contact_interference=20[um]`、`radial_load=0.101[N]`、`inner_radial_displacement=0[um]`。因此简单全局干涉也不是稳定修复路径。
- 2026-07-14 新增并真实运行显式 raceway entity override 诊断 `load_side_group_boundary_load_single_solve_0p101_entity_raceway_override`：基于 saved-MPH 几何矩证据，把 active load-side raceway destination selections 重建为 `Explicit` 边界实体选择，保持同一 `0.101 N` fresh ramp、active rollers `12/1/2`、BoundaryLoad、weak guidance、weak roller foundation、active-roller spring、penalty 和 relaxation 不变。首次运行保存在 `runtime_smoke/bearing_family_p12_boundaryload_entity_raceway_override/bearing3d_load_side_boundaryload_0p101_entity_raceway_override`，求解和 native PNG 导出成功，但 active distribution 仍失败：`roller_1=0.0 Pa`、`roller_2≈9.77e4 Pa`、`roller_12≈1.10e5 Pa`；saved-MPH contact probe 仍显示 `roller_1` pair-specific `Tn=0`。随后修正 setup，使 Explicit selection override 后立刻把对应 Contact Pair destination 重新 `.named(selection_tag)`，并真实 rerun 到 `runtime_smoke/bearing_family_p12_boundaryload_entity_raceway_override_rebind/bearing3d_load_side_boundaryload_0p101_entity_raceway_override_rebind`。rebind 版仍求解并导出 native PNG，但 `roller_1=0.0 Pa`、`roller_2≈9.77e4 Pa`、`roller_12≈1.10e5 Pa`，saved-MPH probe 确认 pair endpoints 已恢复命名且实体计数 `2 -> 2`，但 `roller_1 pair_specific_nonzero_count=0`、gap 仍为 `Infinity`。因此显式复用/重绑这些 raceway 实体不是 production 修复；下一步应做真实几何 partition/imprint 的局部 raceway contact surfaces，或改变 contact-state/gap-closure formulation。最新 stage evidence matrix 为 `121` 个 summary、`273` 个 stage row、`production_ready_count=0`、`reaction_verified_stage_count=0`、`converged_native_stage_count=189`、`saved_contact_probe_report_count=5`。
- 2026-07-14 新增 saved-MPH Contact feature 属性内省：`--probe-contact-mph` 现在把 `contact_roller_{1,2,12}_{inner,outer}` 的 property names、可读属性、allowed values 和候选 offset/gap 属性错误写入 `contact_feature_introspection`。真实 replay 保存在 `runtime_smoke/bearing_family_p12_boundaryload_gapoffset/bearing3d_load_side_boundaryload_0p101_roller1_gapoffset_minus3um/contact_probe_solved_mph_introspection/contact_probe_summary.json` / `.md`，确认 6 个 Contact feature 均可读取；COMSOL 6.2 有 `offset`、`source_offset`、`pressureOffsetCtrl`、`zeroInitGap`，但 `gapoffset`、`gapOffset`、`contactOffset`、`offsetValue`、`initialGap`、`initgap` 均为 unknown parameter。归一化正常的 roller tag 差异后，`roller_1` 的 Contact feature 设置与非零参考滚子 `2/12` 匹配。因此 `gapoffset` 不是可用修复参数，静态 Contact feature setting mismatch 也不是当前主因；下一步应转向真实局部 raceway partition/imprint，或基于有效 `offset/source_offset` 做单变量 contact-state 诊断。最新 stage evidence matrix 为 `122` 个 summary、`274` 个 stage row、`production_ready_count=0`、`reaction_verified_stage_count=0`、`converged_native_stage_count=190`、`saved_contact_probe_report_count=7`。
- 2026-07-14 新增并真实运行有效属性单变量诊断 `load_side_group_boundary_load_single_solve_0p101_roller1_source_offset_minus3um`：保持同一 `0.101 N` fresh BoundaryLoad ramp、active rollers `12/1/2`、weak guidance、weak roller foundation、active-roller spring、penalty 和 relaxation，只把 `contact_roller_1_inner/outer.source_offset` 设为 `-3[um]`。COMSOL 接受属性并完成求解、导出 native Volume PNG，artifact 在 `runtime_smoke/bearing_family_p12_boundaryload_source_offset/bearing3d_load_side_boundaryload_0p101_roller1_source_offset_minus3um`；但 requested-stage selector 正确拒绝，因为 `roller_1=0.0 Pa`、`roller_2≈9.77e4 Pa`、`roller_12≈1.10e5 Pa`。saved-MPH contact replay 仍显示 `roller_1` pair-specific `Tn=0`、gap 为 Infinity sentinel，`roller_2/12` 是唯一 pair-specific 非零参考。因此小负 `source_offset` 不是 production 修复；下一步仍应优先真实局部 raceway partition/imprint，或尝试严格单变量的相反符号/不同有效 offset 设定。最新 stage evidence matrix 为 `123` 个 summary、`275` 个 stage row、`production_ready_count=0`、`reaction_verified_stage_count=0`、`converged_native_stage_count=191`、`saved_contact_probe_report_count=8`。
- 2026-07-14 新增并真实运行相反符号 `load_side_group_boundary_load_single_solve_0p101_roller1_source_offset_plus3um`：仅把上一条的 `source_offset` 从 `-3[um]` 改为 `3[um]`，其他求解、载荷、active rollers、contact penalty/relaxation、weak guidance/foundation 全部不变。COMSOL 同样接受属性、求解并导出 native Volume PNG，artifact 在 `runtime_smoke/bearing_family_p12_boundaryload_source_offset_plus/bearing3d_load_side_boundaryload_0p101_roller1_source_offset_plus3um`；但 requested-stage selector 仍拒绝，`roller_1=0.0 Pa`、`roller_2≈9.77e4 Pa`、`roller_12≈1.10e5 Pa`。saved-MPH replay 再次显示 `roller_1` pair-specific `Tn=0`、gap 为 Infinity sentinel。因此 `source_offset` 小正/小负两种符号均不是 production 修复。最新 stage evidence matrix 为 `124` 个 summary、`276` 个 stage row、`production_ready_count=0`、`reaction_verified_stage_count=0`、`converged_native_stage_count=192`、`saved_contact_probe_report_count=9`。
- 2026-07-14 继续新增并真实运行有效 `offset` 属性双符号诊断 `load_side_group_boundary_load_single_solve_0p101_roller1_offset_minus3um` 与 `load_side_group_boundary_load_single_solve_0p101_roller1_offset_plus3um`：保持同一 `0.101 N` fresh BoundaryLoad ramp、active rollers `12/1/2`、weak guidance、weak roller foundation、active-roller spring、penalty 和 relaxation，只把 `contact_roller_1_inner/outer.offset` 分别设为 `-3[um]` 或 `3[um]`。两次 COMSOL 均接受属性、求解并导出 native Volume PNG，artifacts 在 `runtime_smoke/bearing_family_p12_boundaryload_offset/bearing3d_load_side_boundaryload_0p101_roller1_offset_minus3um` 和 `runtime_smoke/bearing_family_p12_boundaryload_offset_plus/bearing3d_load_side_boundaryload_0p101_roller1_offset_plus3um`；但 requested-stage selector 均正确拒绝：`roller_1=0.0 Pa`，`roller_2≈9.77e4 Pa`，`roller_12≈1.10e5 Pa`，active-roller nonzero ratio 仍为 `2/3`。saved-MPH contact probes 对两次 run 均成功写出报告，确认 `roller_1` destination pair-transfer `solid.Tn_cp_roller_1_inner/outer_raceway` 积分仍为 `0.0`，而 `roller_2/12` outer destination pair-transfer 约 `0.189 N`，inner 约 `0.0011 N`；Contact introspection 也确认 `offset`、`source_offset`、`pressureOffsetCtrl` 和 `zeroInitGap` 为可读有效属性，`gapoffset` 等猜测属性不可用。因此有效 `offset`/`source_offset` 小扰动已被排除，不能作为 design-grade BoundaryLoad 修复；下一步应优先真实局部 raceway partition/imprint 或接触状态/formulation 诊断。最新 stage evidence matrix 为 `126` 个 summary、`278` 个 stage row、`production_ready_count=0`、`reaction_verified_stage_count=0`、`converged_native_stage_count=194`、`saved_contact_probe_report_count=11`。
- 2026-07-14 新增并真实运行几何选择单变量诊断 `load_side_group_boundary_load_single_solve_0p101_roller1_patch_shrink`：保持同一 `0.101 N` fresh BoundaryLoad ramp、active rollers `12/1/2`、weak guidance、weak roller foundation、active-roller spring、penalty 和 relaxation，只把 `roller_1` 的 `box_roller_1_inner_contact_patch` 收窄到 `x=22.6..23.4 mm`、`y=±1 mm`、`z=±4 mm`，`box_roller_1_outer_contact_patch` 收窄到 `x=30.6..31.4 mm`、`y=±1 mm`、`z=±4 mm`。COMSOL 求解并导出 native Volume PNG，artifact 在 `runtime_smoke/bearing_family_p12_boundaryload_patch_shrink/bearing3d_load_side_boundaryload_0p101_roller1_patch_shrink`，但 requested-stage selector 仍拒绝：`roller_1=0.0 Pa`，`roller_2≈9.77e4 Pa`，`roller_12≈1.10e5 Pa`。configured-MPH diagnostic 确认 Box bounds 生效，但 `sel_inner_raceway_1_contact` 仍绑定两个 destination entities `[131,134]`，`sel_outer_raceway_1_contact` 仍绑定两个 entities `[8,9]`；solved-MPH contact probe 仍显示 `roller_1` pair-transfer `Tn=0`，而 `roller_2/12` pair-transfer 非零。几何矩也未恢复为非零邻近滚子的局部 patch 形态：`roller_1` inner/outer source-destination radial deltas 均约 `9.811 mm`，而 `roller_2/12` 约为 `6.006 mm` inner 和 `2.247 mm` outer。因此简单收窄 Box/Intersection selection 不能产生真实局部 raceway contact surface，下一步应实现 geometry-level raceway partition/imprint 或等效局部实体生成，而不是继续调小选择框。最新 stage evidence matrix 为 `127` 个 summary、`279` 个 stage row、`production_ready_count=0`、`reaction_verified_stage_count=0`、`converged_native_stage_count=195`、`saved_contact_probe_report_count=12`。
- 2026-07-13 更新 `load_side_group_boundary_load` 为显式 continuation ladder：3 个载荷侧滚子 `0.1 N -> 0.101 N -> 0.105 N -> 0.12 N -> 0.15 N -> 0.2 N -> 0.5 N -> 1 N -> 5 N -> 20 N -> 50 N`，再 6 滚子 `50 N`，再 12 滚子 `50 N`；其中 `0.101 N`、`0.105 N`、`0.12 N`、`0.15 N`、`0.2 N` 和 `0.5 N` 是为诊断 1 N 求解脆弱性插入的细分点，用户要求的 `0.1 N -> 1 N -> 5 N -> 20 N -> 50 N` 里程碑仍保留。真实 COMSOL 运行 `runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_ladder` 中，旧版 reused parametric sweep 的 `load_side_3_roller_boundary_load_0p1n` 收敛并导出原生 Volume PNG，max von Mises `6.526523e6 Pa`、inner-ring max `1.1007336e7 Pa`、max displacement `2.0064229e-3 m`；`load_side_3_roller_boundary_load_1n` 失败为 `java.lang.NullPointerException`，summary 已保存，但因 COMSOL server 断连未保存 failed MPH。随后代码已改为 post-0.1 N 单点固定载荷 + fresh solver sequence 诊断路径。该结果是 BoundaryLoad bootstrap diagnostic，不是高载荷 12 滚子 production-ready 结果。
- 2026-07-13 checkpoint rerun `runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_ladder_checkpoint` 显示卡点前移到固定载荷 `0.2 N`：`0.1 N` 再次收敛并导出原生 PNG，`0.2 N` 失败为 `java.lang.NullPointerException`。该 run 已保存 pre-solve configured MPH：`stage_models/load_side_3_roller_boundary_load_0p1n_configured.mph` 和 `stage_models/load_side_3_roller_boundary_load_0p2n_configured.mph`，可用于下一步直接诊断 0.2 N 配置模型。下一轮优先从低于 `0.2 N` 的第一步、weak inner guidance 单变量开关、或 0.2 N configured MPH 的 solver/contact 状态检查入手。
- 2026-07-13 fine continuation `runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_ladder_fine012` 将第一步降到 `0.12 N`：`0.1 N` 仍收敛并导出原生 PNG，`0.12 N` configured MPH 已保存但求解失败为 `java.lang.NullPointerException`，failed MPH 因 server 断连未保存。新增 no-solve MPH diagnostic：`diagnostics_0p12n/stage_mph_diagnostic.json` / `.md`，确认 BoundaryLoad、三滚子 contact、weak inner guidance 和 cage fixed 状态按预期存在；stationary study 虽 `useparam=off` 但保留旧 `plistarr=0.001 0.005 0.01 0.05 0.1`，下一轮可单变量清理 study parametric 残留、尝试 `0.105 N`，或改变 weak inner guidance stiffness。
- 2026-07-13 clean-study continuation `runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_ladder_fine0105_useparamoff_last` 确认 `0.105 N` configured MPH 中 `useparam=off`、`pname=['radial_load']`、`plistarr=['0.105']`、`punit=['N']`，BoundaryLoad 和 1/2/12 滚子 contact 设置正确；`0.105 N` 仍因 solid mechanics 非线性不收敛失败（相对步长太小），但已保存 `failed_3d_contact_model.mph`、`direct_3d_bearing_summary.json` 和 `diagnostics_0p105n/stage_mph_diagnostic.json` / `.md`。下一轮应继续单变量尝试低于 `0.105 N` 的第一步、weak inner guidance stiffness 或 contact penalty/relaxation。
- 2026-07-13 `runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_ladder_fine0101` 将第一步进一步降到 `0.101 N`，diagnostic 确认 `useparam=off`、`plistarr=['0.101']`、BoundaryLoad/contact/weak guidance 配置均正确；`0.101 N` 仍因 solid mechanics 非线性不收敛失败并保存 `failed_3d_contact_model.mph`。下一轮更应改变 weak inner guidance stiffness 或 contact penalty/relaxation；继续只降载荷主要用于定位 `0.1 N` 附近的分岔点。
- 2026-07-13 reaction-equivalent probe 新增 selection-bound Java `IntSurface` fallback：在 `intop_displacement_reaction_probe(...)` 继续 unknown operator 时，仍会对 `sel_inner_bore_load_surface` 尝试 `solid.RFx/RFy/RFz` 等 surface integral 候选，并把每个 candidate 的 method、success/value/error 写入 `reaction_equivalent.evaluations`；只有真实 evaluate 成功且反力非零才允许 `reaction_equivalent.success=true`。真实运行 `runtime_smoke/bearing_family_p12_reaction_equivalent/bearing3d_high_preload_reaction_equivalent_intsurface_nonzero_gate` 显示 28 个候选中 6 个 `java_intsurface` 候选可 evaluate，但全部为 `0.0 N`，因此 `reaction_equivalent.success=false`、`successful_candidate_count=0`，仍不能声称 verified reaction/load closure。
- 2026-07-14 reaction-equivalent summary contract 进一步增强：新 run 会写 `reaction_equivalent.setup_audit`、`reaction_equivalent.candidate_audit`，按 `unknown_operator`、`unknown_variable`、`zero_result`、`nonzero_success` 聚合候选，并增加 `solid.T_stress*` 与应力张量牵引项 surface-integral 候选。该改动只增强诊断，不改变成功定义；只有真实非零反力/牵引 evaluate 才能把 `reaction_equivalent.success` 置为 `true`。
- 2026-07-14 对 `bearing3d_high_preload_reaction_equivalent_intsurface_nonzero_gate` 的 configured MPH 与 result-package MPH 做 no-solve audit：configured pre-solve MPH 不含 `intop_displacement_reaction_probe`，因为当前 reaction coupling 是 solve 后创建；result-package MPH 中 coupling 存在，类型为 `Integration`，`opname=intop_displacement_reaction_probe`，selection 绑定 `sel_inner_bore_load_surface` 的 8 个边界实体。代码已改为未来 reaction stage 额外保存 `post_reaction_probe_model_save` MPH，便于复现 post-probe coupling 状态。
- 2026-07-14 真实 rerun `bearing3d_high_preload_reaction_equivalent_current_audit3`：stage 收敛并导出 native PNG，max von Mises `9283.943687400591 Pa`、inner-ring max `10590.748020054052 Pa`、max displacement `2.30970568117654e-4 m`；`setup_audit.success=true`，确认 integration coupling/opname/selection 均正确，post-reaction-probe MPH 和 no-solve diagnostic 已保存。但 40 个候选中 23 个 operator expression 仍 unknown operator，9 个 Java `IntSurface`/traction 候选 evaluate 为 `0.0 N`，8 个为 selection/evaluation error，`successful_candidate_count=0`，因此仍不能声称 verified reaction/load closure。saved-MPH no-solve replay 已记录在 `runtime_smoke/bearing_family_p12_reaction_equivalent/bearing3d_high_preload_reaction_equivalent_current_audit3/reaction_probe_post_mph/reaction_probe_summary.json` / `.md`，并被 stage evidence matrix 索引为未验证反力报告。
- 2026-07-13 soft-guidance diagnostic `runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_soft_guidance_k1e4` 显示：`0.1 N` parametric bootstrap 仍物理合理并导出 native PNG；同样 `0.1 N` 的 single-point 求解虽然返回 success 和 native PNG，但 max von Mises 达 `1.4365898775071404e13 Pa`、inner-ring max 达 `7.590702394553797e13 Pa`、max displacement 达 `20.100776441512814 m`，已被 physical plausibility gate 拒绝。随后 `0.1 N` + weak guidance `1e4[N/m^3]` 失败为 `java.lang.NullPointerException`，configured-MPH no-solve diagnostic 保存在 `diagnostics_0p1n_k1e4/stage_mph_diagnostic.json` / `.md`。该 native PNG 不能作为真实轴承应力图；下一步应单变量调整 contact penalty/relaxation 或 stabilization。
- 2026-07-13 contact-penalty diagnostic `runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_contact_relaxation_penalty1e5` 只把 post-bootstrap contact penalty 从 `5e-5*E_steel` 改到 `1e-5*E_steel`，其余 3 滚子、BoundaryLoad、weak guidance、weak roller foundation、active-roller spring 保持不变。`0.1 N` bootstrap 仍收敛；`0.1 N` softened-penalty single-point 虽收敛并导出 native PNG，但同样爆炸到 `1.4365898775071404e13 Pa` / `20.100776441512814 m`，被 physical plausibility gate 拒绝；`0.101 N` softened-penalty stage 失败为 `java.lang.NullPointerException`。已保存 configured MPH 和 no-solve diagnostic：`stage_models/contact_relaxation_3_roller_boundary_load_0p101n_penalty1e5_configured.mph`、`diagnostics_0p101n_penalty1e5/stage_mph_diagnostic.json` / `.md`。该分支说明单独降 penalty 不足以修复 post-bootstrap load-control，下一步更应改 stabilization/release strategy 或 solver formulation。
- 2026-07-13 micro-parametric continuation `runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_micro_continuation_0p101` 保持 3 滚子、BoundaryLoad、weak guidance、weak roller foundation、active-roller spring、contact penalty/relaxation/mesh/cage-off 不变，只把 post-bootstrap `0.101 N` fixed single-point 改成 `0.1 0.1005 0.101` parametric micro-continuation，并在 `createAutoSequences('sol')` 后重写 `useparam/pname/plistarr/punit`。`0.1 N` bootstrap 仍收敛；`0.101 N` micro-continuation 长时间无 PNG 后中断，summary 记录 `java.lang.NullPointerException`。no-solve diagnostic 确认 configured MPH 中 `useparam=on`、`plistarr=['0.1 0.1005 0.101']`、BoundaryLoad/weak guidance 均正确，因此失败更偏向实际 load-control/contact/stabilization formulation，而不是 stale study setting。artifact：`stage_models/micro_continuation_3_roller_boundary_load_0p101n_parametric_configured.mph`、`diagnostics_0p101n_parametric/stage_mph_diagnostic.json` / `.md`。
- 2026-07-13 fixed-active-roller stabilization diagnostic `runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_fixed_stabilization_0p101` 保持 3 滚子、BoundaryLoad、contact penalty/relaxation、mesh、weak guidance、weak roller foundation、cage-off 不变，只把 post-bootstrap active-roller stabilization 从 spring 改成 fixed roller boundary constraints。`0.1 N` bootstrap 仍收敛；`0.1 N` fixed-active stage 长时间无 PNG 后中断，summary 记录 `java.lang.NullPointerException`。no-solve diagnostic 确认 `useparam=off`、`plistarr=['0.1']`、BoundaryLoad active，且 rollers `1/2/12` 的 `fix_roller_*_stage_stabilization` 为 active。该分支说明把 spring 换成 fixed active rollers 不足以修复 BoundaryLoad，反而在同载荷固定阶段失败；artifact：`stage_models/fixed_stabilization_3_roller_boundary_load_0p1n_fixed_active_configured.mph`、`diagnostics_0p1n_fixed_active/stage_mph_diagnostic.json` / `.md`。
- 2026-07-14 新增并真实运行 `load_side_group_boundary_load_single_solve_0p101`：保持 3 个载荷侧滚子 `12/1/2`、inner-bore `BoundaryLoad`、contact penalty/relaxation、mesh、weak guidance、weak roller foundation、active-roller spring、cage-off 不变，但不先求解 `0.1 N` bootstrap，也不跨 stage 编辑 study/solver，而是在一个 fresh solver sequence 中直接 parametric ramp `0.001 0.005 0.01 0.05 0.1 0.1005 0.101 N`。真实 COMSOL 收敛并导出 native Volume PNG，max von Mises `6.526523284e6 Pa`、inner-ring max `1.100733554e7 Pa`、max displacement `2.214274858e-3 m`、contact-pressure estimate `65.75520833 Pa`。configured MPH 和 diagnostic 分别在 `runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p101/stage_models/single_solve_3_roller_boundary_load_0p101n_parametric_configured.mph`、`diagnostics_0p101n_single_solve/stage_mph_diagnostic.json` / `.md`；diagnostic 确认 `useparam=on`、`plistarr=['0.001 0.005 0.01 0.05 0.1 0.1005 0.101']`、BoundaryLoad active、cage contact inactive、weak guidance active。该分支证明 `0.101 N` 本身可通过单 solver sequence 到达，但仍只是 3-roller low-load diagnostic，不是 12 滚子 high-load/cage production-ready，也没有 verified reaction。
- 2026-07-14 新增并真实运行 `load_side_group_boundary_load_single_solve_0p12`：沿用同一 fresh single-solve formulation，把 parametric ramp 扩展到 `0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 N`。真实 COMSOL 也收敛并导出 native Volume PNG，max von Mises `6.526523284e6 Pa`、inner-ring max `1.100733554e7 Pa`、max displacement `2.727367048e-3 m`、contact-pressure estimate `78.125 Pa`。artifact：`runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p12/direct_3d_bearing_summary.json`、`stage_models/single_solve_3_roller_boundary_load_0p12n_parametric_configured.mph`、`diagnostics_0p12n_single_solve/stage_mph_diagnostic.json` / `.md`。该分支证明 earlier post-bootstrap fixed `0.12 N` failure 不是单纯载荷幅值不可达；但 stress max 重复、仍有 weak guidance 和 temporary active-roller spring，因此下一步应查载荷路径/约束主导并尝试 `0.2/1 N` single-solve 或逐步释放 spring/guidance。
- 2026-07-14 新增并真实运行 `load_side_group_boundary_load_single_solve_0p13`、`load_side_group_boundary_load_single_solve_0p14`、`load_side_group_boundary_load_single_solve_0p145`、`load_side_group_boundary_load_single_solve_0p1475`、`load_side_group_boundary_load_single_solve_0p14875`、`load_side_group_boundary_load_single_solve_0p149375`、`load_side_group_boundary_load_single_solve_0p15_fine`、`load_side_group_boundary_load_single_solve_0p1625`、`load_side_group_boundary_load_single_solve_0p175`、`load_side_group_boundary_load_single_solve_0p1875`、`load_side_group_boundary_load_single_solve_0p19375`、`load_side_group_boundary_load_single_solve_0p196875`、`load_side_group_boundary_load_single_solve_0p1984375` 和 `load_side_group_boundary_load_single_solve_0p2_fine`：继续沿用同一 fresh single-solve formulation，把 parametric ramp 细化到 `0.2 N`。这些 stage 均真实收敛并导出 native Volume PNG。`0.13 N`：max von Mises `6.526523284e6 Pa`、inner-ring max `1.100733554e7 Pa`、max displacement `3.122212334e-3 m`、contact-pressure estimate `84.63541667 Pa`；artifact 在 `runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p13/`。`0.14 N`：max displacement `3.545713204e-3 m`；`0.145 N`：max displacement `3.763421798e-3 m`；`0.1475 N`：max displacement `3.878676165e-3 m`；`0.14875 N`：max displacement `3.936759582e-3 m`；`0.149375 N`：max displacement `3.965742682e-3 m`；fine `0.15 N`：max displacement `3.994913732e-3 m`；`0.1625 N`：max displacement `4.610957949e-3 m`；`0.175 N`：max displacement `5.280893802e-3 m`；`0.1875 N`：max displacement `6.017368225e-3 m`；`0.19375 N`：max displacement `6.411106625e-3 m`；`0.196875 N`：max displacement `6.534775763e-3 m`；`0.1984375 N`：max displacement `6.552863781e-3 m`；fine `0.2 N`：max displacement `6.570435359e-3 m`。这些 stage 的 max von Mises 均停在 `6.526523284e6 Pa`、inner-ring max 均停在 `1.100733554e7 Pa`，说明 stress plateau/constraint dominance 仍需诊断。configured MPH 的 no-solve diagnostics 均确认 BoundaryLoad active、displacement preload inactive、rollers `1/2/12` contact active、cage contact inactive、weak guidance active。该分支把 fresh-solver BoundaryLoad 可收敛诊断推进到 fine `0.2 N`，但仍是 3-roller low-load diagnostic，不是 12 滚子 high-load/cage production-ready，也没有 verified reaction。
- 2026-07-14 粗步长 `load_side_group_boundary_load_single_solve_0p15` 曾失败：它从 `0.12 N` 直接跳到 `0.15 N`，保存 configured MPH 后长时间无 native PNG，人工中断后 summary 记录 `Solve failed: java.lang.NullPointerException`。随后新增 fine continuation `load_side_group_boundary_load_single_solve_0p15_fine`，在 `0.12 N` 和 `0.15 N` 之间插入 `0.13 0.14 0.145 0.1475 0.14875 0.149375 N`，真实 COMSOL 收敛并导出 native PNG。因此旧 `0.15 N` 失败现在归类为 continuation-step sensitivity 证据，而不是绝对载荷幅值不可达。artifact：`runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p15_fine/direct_3d_bearing_summary.json`、`stage_models/single_solve_3_roller_boundary_load_0p15n_fine_parametric_configured.mph`、`diagnostics_0p15n_fine_single_solve/stage_mph_diagnostic.json` / `.md`。
- 2026-07-14 粗 `load_side_group_boundary_load_single_solve_0p2` 曾失败：它从 `0.15 N` 直接跳到 `0.2 N`，保存 configured MPH 后长时间无 native PNG，人工中断后 summary 记录 `Solve failed: java.lang.NullPointerException`。随后新增 fine continuation `load_side_group_boundary_load_single_solve_0p2_fine`，在 `0.15 N` 与 `0.2 N` 之间保留 `0.1625 0.175 0.1875 0.19375 0.196875 0.1984375 N`，真实 COMSOL 收敛并导出 native PNG。因此旧 `0.2 N` 失败现在归类为 continuation-step sensitivity 证据，而不是绝对载荷幅值不可达。artifact：`runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p2_fine/direct_3d_bearing_summary.json`、`stage_models/single_solve_3_roller_boundary_load_0p2n_fine_parametric_configured.mph`、`diagnostics_0p2n_fine_single_solve/stage_mph_diagnostic.json` / `.md`。下一步不要直接宣称 `1 N` 为设计级结果；应优先诊断 stress plateau/约束主导、过大位移、weak guidance/temporary spring 影响和反力未验证问题，再决定是否继续向 `0.5 N`/`1 N` continuation 推进。

限制：

- `legacy_raceway_highload_direct` 是 12 滚子 raceway-only 高载荷可视化层，使用内圈分布式 BodyLoad，必须标注 `visual_fallback_inner_ring_distributed_body_load_not_design_boundary_load`。
- 完整 3D cage-pocket 接触载荷传递和设计级 inner-bore BoundaryLoad 高载荷收敛仍未宣布完成；失败时必须保留错误和 artifact，不得伪造成功。下一轮优先诊断 `roller_1` 的 contact-state/gap closure 与 geometry-level raceway partition/imprint，而不是继续重复静态 selection/feature 设置、source/destination 翻转、full-raceway destination、全局干涉或显式实体复用；同时继续反力/载荷闭合诊断。修复后再尝试 `0.5 N`、`1 N`、6/12 滚子和 cage。不要重复把当前 reaction-equivalent、3-roller bootstrap、`0.101/0.12/0.13/0.14/0.145/0.1475/0.14875/0.149375/0.15/0.1625/0.175/0.1875/0.19375/0.196875/0.1984375/0.2 N` single-solve 诊断、entity override/rebind 诊断或 coarse failed `0.2 N` configured MPH 当作已验证等效载荷。

## 后续阶段

### F1 首批模板与生成 smoke

目标：每个模型族先做“最小可运行”案例，再逐步提高真实度。

偏心轴：

- 模板：3D cylinder + offset disk/mass 或偏心圆柱段。
- 物理：Solid Mechanics，固定/轴承支撑简化，转动或等效离心载荷。
- 输出：`solid.mises`, `solid.disp`, 最大位移，PNG。
- smoke：可先静态等效载荷，后续再加模态/频响。

齿轮：

- 模板：先做 2D/3D 单齿或简化齿轮副接触，不一开始追求完整渐开线生产模型。
- 物理：Solid Mechanics + Contact pair。
- 输出：齿根 von Mises、接触压力、位移。
- smoke：先验证 contact pair、边界选择、非零应力；再扩展真实齿形。

PCB：

- 已有起点：P12 `pcb_thermal_plate_seed` 提供工程级纯热 starter template。
- 下一步：真实 COMSOL smoke，复核几何域/边界选择、材料绑定和温度输出。
- 第二阶段：加入 Electric Currents 和 Joule Heating，扩展到电热耦合。
- 输出：最高温度、温升云图；电热耦合阶段再加入电流密度。

### F2 通用质量门

目标：把轴承 quality gate 的经验变成通用检查框架。

通用检查：

- 禁止危险 Java/API 片段。
- 必须创建 component、geometry、material、physics、mesh、study、result。
- 必须有单位化参数。
- 必须有明确输出表达式。
- 不能在 setup 代码里直接 solve 或执行文件系统危险操作。

模型族检查：

- 偏心轴：必须存在偏心量/转速或等效载荷；必须有支撑/约束；输出应力和位移。
- 齿轮：必须有两个接触实体或单齿接触简化；必须说明齿形/接触假设；接触区局部网格。
- PCB：必须有板材、铜/导体、热源或电激励；必须有散热边界；输出温度。
- 轴承：沿用现有 roller/contact/cage/selection binding 检查。

### F3 结果包与报告通用化

目标：新增 `simulation_export_model_package`，让报告不再只叫 bearing package。

通用包内容：

- `summary.json`
- `report.md`
- `.mph` 模型路径
- plot 路径
- 模板/生成代码 lineage
- requirement slots
- assumptions
- metrics
- quality_gate
- verification_status

领域指标：

- 偏心轴：最大应力、最大位移、危险截面、模态频率。
- 齿轮：齿根应力、接触压力、啮合区、网格/接触收敛状态。
- PCB：最高温度、热点位置、电流密度、电热耦合状态。
- 轴承：继续记录接触压力、保持架/滚子/选择集绑定和收敛证据。

### F4 Demo、测试和文档

目标：让多模型族能力可回归、可展示、可继续迭代。

建议新增：

- `scripts/run_agent_general_model_demo.py --case eccentric_shaft --print-prompts`
- `scripts/run_agent_general_model_demo.py --case gear_pair --print-prompts`
- `scripts/run_agent_general_model_demo.py --case pcb_thermal --print-prompts`
- `tests/test_modeling_request_planner.py`
- `tests/test_model_family_registry.py`
- `tests/test_general_model_package.py`

离线验收：

```bash
python3 -m compileall -q comsol_agent tests scripts
python3 -m pytest -q
python3 scripts/run_agent_general_model_demo.py --case eccentric_shaft --print-prompts
python3 scripts/run_agent_general_model_demo.py --case gear_pair --print-prompts
python3 scripts/run_agent_general_model_demo.py --case pcb_thermal --print-prompts
```

真实 COMSOL 验收：

```bash
.venv/bin/python scripts/run_agent_general_model_demo.py --case eccentric_shaft --cores 1
.venv/bin/python scripts/run_agent_general_model_demo.py --case pcb_thermal --cores 1
.venv/bin/python scripts/run_agent_general_model_demo.py --case gear_pair --cores 1
```

齿轮 contact smoke 可作为第二优先级，因为它比偏心轴和 PCB 热模型更容易受到接触设置和网格影响。

## 推荐实现顺序

1. 合并/完成当前需求槽位开发，确保跨轮需求记忆可靠。
2. 新增 `simulation_plan_modeling_request`，先复用现有 `simulation_plan_generated_code`，不要马上重写生成链路。
3. 新增 `ModelFamilySpec` registry，并把轴承 skill 迁入 registry。
4. 增加偏心轴和 PCB 的最小模板，因为它们比齿轮接触更容易稳定验证。
5. 抽象通用 `simulation_export_model_package`。
6. 增加齿轮简化接触模板和专属质量门。
7. 把 prompt 和文档改为“通用建模 Agent”，轴承作为高质量示例而不是默认边界。

## 近期任务清单

| 优先级 | 任务 | 主要文件 | 验收 |
| --- | --- | --- | --- |
| P0 | 补全需求槽位 schema | `comsol_agent/memory/requirements.py` | 能识别偏心轴、齿轮、PCB 的几何/物理/载荷/输出 |
| P0 | 新增通用 planner 工具 | `comsol_agent/tools/simulation.py`, `tools_bootstrap.py` | 工具返回 model_family、missing_decisions、next_tool_chain |
| P0 | 建立模型族 registry | `comsol_agent/simulation/skills.py` 或新模块 | 轴承、偏心轴、齿轮、PCB 都可注册/搜索 |
| P1 | 偏心轴 starter template | `skills.py`, tests | 离线 validate 通过，真实 COMSOL smoke 可生成非零应力 |
| P1 | PCB 热 starter template | `skills.py`, tests | 最高温度/温升输出可评估 |
| P1 | 通用 result package | `tools/simulation.py`, `artifact_reader.py` | 结果包不依赖 bearing 命名 |
| P2 | 齿轮接触 starter template | `skills.py`, tests, smoke script | 接触区非零应力，明确简化假设 |
| P2 | 通用 demo script | `scripts/run_agent_general_model_demo.py` | 三个 case 都支持 `--print-prompts` |
| P2 | 文档与 CLI 帮助更新 | `docs/comsol_runtime.md`, `README.md`, renderer | 用户能看到“多模型通用建模”路径 |

## 风险与处理

- 风险：每个模型族都写成一套孤立 planner，代码膨胀。处理：先做通用 planner + registry，专属 planner 只补充领域规则。
- 风险：齿轮/轴承接触模型真实 COMSOL 收敛慢。处理：先用简化 smoke，报告中明确假设和未验证项。
- 风险：LLM 把模板当成强约束，遇到新模型仍套轴承逻辑。处理：planner 输出必须包含 `model_family` 和 `template_policy.use_template_if_fit`，prompt 明确“模板不匹配则 generated-code”。
- 风险：结果报告指标过于轴承化。处理：新增通用 package schema，领域指标放在 `domain_metrics` 下。

## 完成标准

第一阶段完成时，用户应该可以提出以下请求，Agent 不会回落成轴承模板：

- “做一个偏心轴，钢材，轴端固定，偏心段受 3000 rpm 等效载荷，输出应力和位移。”
- “做一个 PCB 热仿真，FR4 板上有两个 5W 芯片，底面对流散热，输出最高温度。”
- “做一个简化齿轮副接触模型，给定扭矩，输出齿根应力和接触压力。”

每个请求至少应产生：

- 结构化需求拆解；
- 模板匹配或 generated-code fallback 决策；
- 验证过的 COMSOL Java/API setup code；
- 可追踪 artifact；
- 结果包和报告；
- 明确的模型简化假设与下一步精化建议。
