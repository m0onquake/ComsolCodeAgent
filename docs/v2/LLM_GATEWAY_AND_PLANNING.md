# V2 Model Gateway、自然语言 Intake 与 Planner

## 1. 边界

M7.5 的 LLM 只有解释、计划和有限候选生成职责。`BearingSpec`、`ChangeSet`、Registry、
Policy、COMSOL Runtime 和 Auditor 仍是合同、权限与事实来源。LLM 不能声明 solve/audit/
memory promotion 成功，不能增加工具权限，也不能为已支持参数变更重写整个模型。

## 2. Model Gateway

`comsol_agent/v2/model_gateway/` 定义版本化 `ModelRequest`、`ModelResponse`、`ModelError`、
`Usage`、`StructuredOutput` 和 `ModelToolCall`。Gateway 提供：

- 注入式 fake、prompt-digest record/replay 和真实 OpenAI-compatible adapter；
- provider/model、内部 request id、provider request id、UTC 时间、Prompt/schema 版本、token
  usage、输出来源和 SHA-256 prompt digest；
- timeout、取消、有限重试、输出/token/费用预算与结构化错误；
- 顶层 JSON object 和 JSON Schema 本地复验。非法结构在 Planner/Runtime 之前失败。

API key 仅由现有 config/环境变量读取，不进入 request、Trace、回放记录或证据摘要。

## 3. Bearing Intake

`BearingNaturalLanguageIntake` 将单轮或多轮中文需求转为 `BearingRequirementDraft`，再由本地
`BearingSpec` 复验。每个值标记 `explicit`、`inherited`、`default` 或 `derived`。缺少关键初始
几何时返回 clarification；几何冲突返回 invalid；非圆柱滚子轴承、轴向或联合载荷返回
unsupported。模型不得用默认值冒充用户显式值。

## 4. Planner 和 RAG

`BearingPlanner` 输入 `GoalSpec`、当前/请求规格、权威 `ChangeSet`、Registry snapshot、预算和
`ContextPack`。LLM 输出只是 `BearingPlanDraft`；本地 Policy 要求：

- route 必须与 `classify_changes()` 一致；
- capability 必须来自当前 Registry snapshot 的 schema 枚举；
- 传入 RAG 时必须保留至少一个真实 record id，且不得引用未提供记录；
- 参数变更只生成 parameter override → continuation → strict audit；几何变更调用
  registered deterministic Builder；两者都不允许 LLM 整模型生成。

Registry 输入必须是不可变 `ExtensionSnapshot`，不接受由提示词或调用者伪造的
capability 字符串列表。Planner 生成的可执行 Action 固定 Function、Builder、Path 和
Auditor 的 ID/version/kind/capability；`RegistryToolExecutor` 与轴承工作流在 COMSOL
调用前再次校验这些 pin。伪造版本、未注册 capability、schema 或权限一律在
求解前拒绝。

Context Pack 在 Prompt 中明确标记为 untrusted quoted data。RAG 引用可追溯，但不变成执行权限
或物理真理。

## 5. 受限 LLM Repair

`RestrictedLLMPatchProvider` 仅返回 M3 `PatchSet`/`TextReplacement`，且只允许 Diagnosis 中的精确
文件路径、单次命中替换、有限替换数和局部文本大小。它是 M6 `CandidateProvider`，因此
只在 deterministic rule、local pattern 和严格 RepairCase 之后被考虑，并继承 checkpoint、尝试预算、
verifier、rollback 和强制 gates。候选不能输出或执行 Shell/Java/Python 程序或整文件/整模型替换。

## 6. 验证层级

普通 pytest 只使用 fake/replay，不消耗外部 token。真实 LLM 是显式 opt-in：

```bash
.venv/bin/python scripts/run_v2_llm_gate.py
.venv/bin/python scripts/run_v2_llm_gate.py --run-comsol --cores 1 --comsol-timeout-seconds 1200
```

第二条从中文需求开始，经真实 Intake/Planner 生成类型化 Plan，再由
`AgentKernel` 通过固定 Registry snapshot 执行轴承工作流、M5 Runtime 和严格 Auditor。
完整运行 artifact 保存在 `reports/`，Git 只保存脱敏摘要与哈希。普通 pytest 不调用
DeepSeek，所以 API 控制台无 token 消耗是预期行为；只有显式运行上述 gate 才会产生
并保存真实 usage。
