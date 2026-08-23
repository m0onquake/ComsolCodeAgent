# ADR 0008: 受控 Model Gateway 与 LLM 解释/规划边界

- 状态：Accepted
- 日期：2026-08-23
- 决策者：COMSOL Agent V2 maintainers
- 替代：无
- 被替代：无

## 上下文

M1–M7 已有领域中立 Kernel、动态扩展、受控 Runtime、RAG、有限 Repair 和确定性轴承 Builder，
但 M7 真实 gate 直接提供类型化规格，`llm_calls=0`。若直接复用 V1 单体 Agent，LLM 将同时
拥有语义理解、工具选择和代码执行影响，难以证明结构、权限、回放和预算边界。

## 候选方案

1. 继续使用 V1 AgentLoop 自由工具调用：集成快，但输出和权限难以局部验证。
2. 让 LLM 生成完整 COMSOL 模型代码：灵活，但违反最小变更路径和 M7 确定性合同。
3. 建立领域中立 Gateway，LLM 只生成严格 Intake/Plan/局部 Patch 候选，再由本地合同和 Policy
   复验。

## 决策

采用方案 3。Model Gateway 统一 fake、replay 和真实 provider，保存 Prompt/schema 版本、请求
ID、时间、usage、来源和 digest，且在本地验证 JSON Schema。领域 Intake/Planner 位于轴承扩展
边界，不进入 Kernel。Planner 输出是 proposal；ChangeSet、Registry snapshot、Policy 和预算决定可执行
Plan。RAG 只以带引用、无权限的数据注入。LLM repair 只能产生严格 exact `PatchSet`。

## 后果

正面影响是真实 token 消耗、输出来源和路由决策可观测，fake/replay 可进入普通回归，同拓扑
参数修改继续保持零 LLM 整模型重写。成本是 Prompt/schema 必须版本化，provider 差异需适配，真实
LLM gate 有外部成本和波动。任何 schema 或 Policy 不一致都安全停止，不自动扩权。

## 验证

- fake/replay 覆盖 JSON Schema、取消、回放 miss、中文 Intake、多轮继承、澄清/冲突/不支持、
  RAG 引用、route/capability 注入拒绝和局部 PatchSet 范围；
- 真实 DeepSeek smoke 保存非零 usage、provider/model、Prompt/schema 版本和脱敏 Trace；
- 真实中文需求经 Intake/Planner、确定性 Builder、COMSOL 6.2 和严格物理 Auditor 通过；
- Kernel 领域中立测试和 M1–M7.5 联合回归通过。
