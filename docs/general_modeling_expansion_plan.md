# 通用建模能力扩展开发计划

Last updated: 2026-07-05

当前分支：`codex/segmented-3d-generation`

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

## 计划分期

### P11.0 分支同步与边界确认

目标：和正在进行的“需求建模拆解”开发保持兼容，避免互相覆盖。

任务：

1. 保留当前 `RequirementState` 的未提交开发，不在计划阶段改动其实现文件。
2. 把本计划作为文档入口提交，供并行开发对齐。
3. 后续实现前先检查 `git status` 和最新 diff，确认另一个对话是否已经完成通用需求槽位。

验收：

- 文档中明确通用化方向、首批模型族、模块拆分和验收标准。
- 不覆盖当前工作区里已有的 AgentLoop / memory / tests 改动。

### P11.1 通用需求槽位升级

目标：把需求建模拆解从“有限关键词记忆”升级成可承载多模型族的结构化需求对象。

建议新增或扩展字段：

- `model_family`: bearing, eccentric_shaft, gear_pair, pcb, heat_sink, bracket, pipe, general。
- `geometry`: 2D/3D、尺寸、几何构成、对称性、参数化变量。
- `physics`: Solid Mechanics, Heat Transfer, Electric Currents, Magnetic Fields, Laminar Flow 等。
- `materials`: 材料名、关键物性、各部件材料映射。
- `boundary_conditions`: 固定、支撑、温度、入口出口、电势、接地等。
- `loads_or_excitations`: 力、压力、扭矩、转速、电流、电压、热源、功率。
- `interfaces`: 接触、粘结、绝缘、热接触、电连接、齿面啮合等。
- `study_type`: stationary, time dependent, frequency, eigenfrequency, parametric sweep。
- `outputs`: 应力、位移、温度、电势、电流密度、接触压力、频率响应、PNG/报告。
- `mesh_requirements`: 局部细化区域、接触区、薄层、过孔、齿根等。
- `verification_requirements`: 非零物理量、选择集绑定、收敛、网格敏感性、能量/载荷平衡。
- `assumptions`: 默认值和简化假设。

代码落点：

- 扩展 `comsol_agent/memory/requirements.py` 的 slot 和关键词，但最终应支持更结构化的 `RequirementState.to_modeling_request()`。
- 更新 `AgentLoop._prepare_tool_call()`，不仅能补 `known_params`，也能补 `model_family`、`domain` 和 `verification_requirements`。
- 增加单测：跨轮输入“先做偏心轴，再补转速和材料”时，后续 `simulation_plan_generated_code` 能收到完整需求。

### P11.2 通用建模规划入口

目标：新增一个不带轴承偏见的高层工具，例如 `simulation_plan_modeling_request`。

输入：

- `user_request`
- `known_params`
- `allow_defaults`
- `preferred_model_name`
- `archive_path`

输出：

- `model_family`
- `domain`
- `ready_to_generate`
- `missing_decisions`
- `follow_up_questions`
- `template_policy`
- `recommended_workflow`
- `quality_contract`
- `next_tool_chain`

路由策略：

- 明确轴承/滚子/保持架：进入现有轴承 planner 或 3D bearing contract。
- 明确偏心轴/转轴/转子：进入 `eccentric_shaft` family planner。
- 明确齿轮/啮合/齿面：进入 `gear_pair` family planner。
- 明确 PCB/电路板/铜层/器件/过孔：进入 `pcb_thermal_electric` family planner。
- 不明确但物理场明确：走通用 generated-code planner。
- 信息不足且 `allow_defaults=false`：只问必要问题，不生成代码。

### P11.3 模型族注册表

目标：把 `SimulationSkill` 扩展为更完整的模型族注册机制。

建议结构：

```python
ModelFamilySpec(
    name="gear_pair",
    domain="structural",
    keywords=(...),
    required_slots=(...),
    default_assumptions={...},
    starter_templates=(...),
    output_expressions=(...),
    quality_gate="validate_gear_pair_code_draft",
)
```

首批规格：

- `eccentric_shaft`: 偏心半径、轴长、轴径、材料、转速/载荷、支撑方式、输出应力/位移/模态。
- `gear_pair`: 模数、齿数、压力角、齿宽、材料、扭矩、接触/啮合简化、输出齿根应力/接触压力。
- `pcb_thermal_electric`: 板尺寸、层数、铜厚、基材、器件功率、电流/电压、散热边界、输出温升/电流密度。
- `bearing_contact`: 迁移现有轴承 skill，使其也服从同一 registry。

验收：

- `simulation_search_templates` 可按模型族或 domain 找到相关 starter template。
- 系统 prompt 不再硬编码过多轴承专属规则，而是引用通用 planner 的返回结果。

### P11.4 首批模板与生成 smoke

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

- 模板：矩形 FR4 板 + 铜走线/面 + 热源芯片。
- 物理：Heat Transfer 起步；第二阶段加 Electric Currents 和 Joule Heating。
- 输出：最高温度、温升云图、电流密度。
- smoke：先热传导稳定求解，再加电热耦合。

### P11.5 通用质量门

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

### P11.6 结果包与报告通用化

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

### P11.7 Demo、测试和文档

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
