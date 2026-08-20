# ADR 0002: 扩展信任、生命周期与确定性解析策略

- 状态：Accepted
- 日期：2026-08-20
- 决策者：项目维护者
- 替代：无
- 被替代：无

## 上下文

ADR 0001 确定了扩展优先、领域无关 Kernel 的方向。M2 需要进一步冻结可执行扩展的信任边界、
权限与兼容检查时机、运行中热更新语义，以及多个扩展声明同一能力时的确定性行为。若这些规则
只存在于 Loader 或调用方的约定中，扩展可以绕过校验，运行中的 Goal 也可能因启停或卸载而
改变行为。

## 候选方案

1. 发现时立即导入扩展，以 Python 导入是否成功作为有效性判断。
2. Registry 允许覆盖同 ID 或同能力扩展，并由加载顺序决定最终实现。
3. 将声明发现与可信代码加载分成两阶段，以严格合同、权限上限和兼容策略做硬门禁；Registry
   显式管理生命周期、冲突与依赖，运行通过不可变快照固定扩展集合。

## 决策

采用方案 3。

- Manifest 使用 `comsol-agent/v2alpha1` API 和严格 Pydantic 合同，可直接生成 JSON Schema；
  配置使用 Draft 2020-12 JSON Schema 校验。
- Discovery 只读取 YAML/JSON，不导入代码。Loader 仅加载位于可信 manifest 根中的声明，且
  entrypoint 模块来源必须位于可信代码根。直接向 Registry 注册实例属于宿主进程内的可信装配，
  不能作为不可信安装入口。
- Loader 按 Python 实际生效的逐级导入解析检查 `sys.path`，并优先检查 `sys.modules` 中已有模块
  和父包；不能因后续路径中存在可信同名模块而放行前置不可信模块。导入后还必须复验实际来源
  与校验来源一致。
- 扩展声明四类显式权限；安装策略设置每类权限上限。Agent API、COMSOL 和依赖版本不兼容时
  硬拒绝，不允许仅告警后继续。
- 生命周期状态为 `registered`、`disabled`、`active` 和 `unhealthy`。逐扩展生命周期锁串行化
  enable、disable、health 与延迟清理；disable 必须在等待 `deactivate()` 前发布 `disabled` 状态，
  过渡期间拒绝卸载。启用与健康检查失败只影响当前扩展；存在扩展 ID/版本依赖或唯一 capability
  provider 依赖时拒绝卸载。
- Resolver 依次执行种类/能力、显式选择、权限、前置条件、优先级、质量和健康过滤。最高候选
  仍同分时返回结构化冲突，不使用加载顺序或随机选择。
- 每次 Agent 运行使用异步租约式 `ExtensionSnapshot` 固定 active 扩展及版本。禁用立即阻止新
  解析，但已有快照释放前延迟 deactivation 并拒绝卸载，因此 Registry 热更新不破坏运行中 Goal。
- Function 和 MCP Tool 通过 `RegistryToolExecutor` 满足 Kernel 的既有 `ToolExecutor` 协议；
  输入输出 schema、动作权限和异常都在扩展边界检查，失败标准化为 `Observation`。Kernel 不导入
  Registry 或具体扩展。

## 后果

正面影响：

- 不可信声明可以被检查而不执行代码；扩展故障、冲突和权限拒绝均可诊断且不会拖垮批量加载。
- 运行具备稳定的扩展版本视图，历史 RunManifest 可记录快照版本；显式关闭快照后才释放资源。
- 新增 Function、MCP、Skill、Hook、规则、路径和领域服务无需增加 Kernel 条件分支。

成本与风险：

- 宿主必须维护可信根和权限上限；Python 扩展仍属于受信任代码，不等同于进程级沙箱。
- 热更新只对新快照生效，长运行若要升级扩展必须显式重启或恢复到新运行。
- 依赖采用显式扩展 ID/版本范围或 `(kind, capability)` 要求；调用关系不会从自由文本自动推断，
  路径/Skill 作者必须在 manifest 声明依赖。

## 验证

- 合同测试覆盖 manifest JSON Schema、配置 schema、兼容性和权限硬拒绝。
- 可信加载测试覆盖 `sys.path` 前置同名模块、`sys.modules` 缓存旧模块和攻击模块零执行。
- 生命周期测试覆盖发现、加载、注册、启停、健康、卸载、重复 ID、缺失/反向依赖和固定快照。
- 并发测试使用阻塞式 `deactivate()` 验证等待期间立即停止解析/租用，并保护过渡期卸载。
- Resolver 测试覆盖显式选择、优先级与结构化冲突。
- 故障测试覆盖 activation、handler 和接口错误隔离；Kernel 集成测试仅通过
  `ToolExecutor` 协议执行动态 Function。
