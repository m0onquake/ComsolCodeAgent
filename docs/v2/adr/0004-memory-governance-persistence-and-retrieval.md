# ADR 0004: 记忆治理、持久化与检索执行门禁

- 状态：Accepted
- 日期：2026-08-21
- 决策者：项目维护者
- 替代：无
- 被替代：无

## 上下文

M4 需要保存成功、失败、修复、规则和 artifact 关系，同时阻止历史相似文本绕过当前版本、拓扑、
引用和审计门禁。如果写入方可以直接声明 `verified`，或检索只按 embedding 排序，不兼容、缺失
artifact、未复验修复和迁移旧案例都可能成为可执行基线。持久化格式、删除语义和版本失效也必须
稳定，否则无法复现检索决策或安全升级。

## 候选方案

1. 将对话、代码和运行日志全部写入同一个向量库，以相似度作为可信度和排序依据。
2. 让各调用方自行设置案例状态；检索后由 LLM 判断是否兼容，删除直接改写或清空数据库。
3. 分离运行态与长期记忆，长期记录采用严格版本合同；新记录统一进入 quarantine，经显式治理
   状态机晋升；检索先做兼容、状态、错误签名和引用硬过滤，再融合可配置检索通道；删除移除内容
   并保留不含内容的 tombstone。

## 决策

采用方案 3。

- Working/Session 只存在于 `RuntimeMemory`，不会因为普通 Observation 自动进入长期存储。
  Episodic/Semantic/Procedural 使用 `MemoryRecord`，Artifact 层只保存带哈希的引用，不内联大文件。
- `MemoryRecord` 使用 `1.0` 严格 schema，记录类型、状态、结构化内容、provenance、兼容范围、质量、
  引用和关系。参考持久化实现是原子替换的版本化 JSON 快照；其他 Memory Adapter 可以使用数据库，
  但必须保持同一合同、状态机和删除语义。快照目录属于可信本地存储，不把任意外部快照视为可信
  安装源。
- Repository 拒绝直接新增非 quarantine 记录，也拒绝未声明治理的状态变化。`MemoryGovernance`
  是 quarantine、candidate、active/verified、needs_revalidation 和 invalidated 转换的唯一公共路径。
- VerifiedCase 晋升要求最终规格、全阶段执行、目标参数步、全部严格物理门禁、可读取且哈希完整的
  artifact、完整 provenance 和无高等级未解决警告。RepairCase 自动使用要求静态与 runtime 复验；
  `physical=null` 只表示该修复不单独声明物理正确性。
- 检索先按 domain、topology、状态池、COMSOL/Agent/Builder/合同版本、作用域和 RepairCase 错误签名
  硬过滤。可执行命中还必须重新验证 artifact 引用与哈希；失败立即转为 `needs_revalidation`。
  之后才融合结构化参数距离、BM25、向量、关系、审计质量、新鲜度和历史采用成功率。权重是合同
  配置，不是 Kernel 常量。
- Context Pack 最多包含一个主成功案例、两个辅助案例和一个匹配修复案例，只暴露接口/差异、
  artifact 引用、来源、可信度与 `fact/case/suggestion/observation` 角色，不内联历史完整代码。
- 删除从活动存储中移除记录内容，只保留记录 ID、删除原因、时间和 provenance 摘要哈希的
  tombstone，防止被重新导入或检索。迁移工具对历史 RunManifest 只生成 quarantined
  `candidate_case`，即使旧 manifest 写有 completed 或 audit passed 也不自动晋升。
- 检索评估记录实际采用、首次执行、严格审计和修复结果，并把采用成功率回写质量字段。文本相似度
  仅作为候选排序信号，不能构成 M4 成功证据。

## 后果

正面影响：

- 未审计、失效、不兼容、引用损坏和错误签名不符的案例不能成为可执行基线。
- 检索决策、Context Pack、晋升和删除均可复现并保留 provenance。
- 可替换向量器、数据库或图后端而不改变 Kernel 和治理合同。

成本与风险：

- 可执行检索要求调用方提供完整运行兼容信息和当前 artifact catalog；缺失信息会安全拒绝。
- JSON 快照是本地参考后端，不提供多进程事务或恶意篡改防护；生产并发存储应由 Memory Adapter
  实现相同的乐观状态检查和原子语义。
- 依赖无关的 hashing vectorizer 用于确定性测试与离线参考；部署可注入受治理的 embedding 模型，
  但不能改变硬过滤和执行门禁。

## 验证

- 合同测试覆盖严格 schema、类型内容、运行态/长期层级隔离和持久化 round trip。
- 治理测试覆盖强制 quarantine、未审计 VerifiedCase、未复验 RepairCase、直接绕过治理、失效、
  重验证和删除 tombstone。
- 混合检索测试覆盖兼容案例命中、拓扑/版本拒绝、BM25/向量/关系通道、引用损坏降级和错误签名
  精确适用。
- Context Pack 测试证明数量边界、角色和引用式内容；迁移测试证明幂等 quarantine。
- 评估测试以采用后的执行和审计结果计算成功率，并回写案例历史采用成功率。
