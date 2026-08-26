# V2 Web、CLI 与可观测性

## 1. 状态语义

M8 将运行生命周期与工程证据分开。`created/running/pause_requested/paused/cancelling/
cancelled/failed/completed` 只描述 Agent 会话；以下四个 Gate 分别保存自己的来源、状态和证据：

| Gate | 含义 | 不代表 |
|---|---|---|
| A `static_validation` | 规格和输入合同通过 | COMSOL 已建模 |
| B `model_build` | Builder、几何、物理配置和网格通过 | 求解收敛 |
| C `solve` | 目标研究/参数步求解通过 | 物理审计通过 |
| D `physical_audit` | 版本化严格 Auditor 全部通过 | 自动晋升 verified memory |

静态案例回放使用原兼容入口，不写入 V2 Gate。V2 `completed` 仍须结合
`verification_level` 和四个 Gate 解读；`plan_only` 可以完成规划，但不能显示 B/C/D 通过。

## 2. 事件合同

`V2Event` 是 Web SSE 与 CLI 的共同来源，包含单调 `sequence`、session/turn、kind、phase、status、
source、message、data 和 UTC 时间。事件种类覆盖：

- specification、retrieval、plan；
- tool 与 COMSOL A-D 实时阶段；
- repair、budget、audit、artifact；
- session 控制与结构化 failure。

`ComsolRuntime(stage_sink=...)` 在真实阶段切换时发送 `RuntimeStageEvent`。sink 故障被隔离，不能改变
COMSOL 执行事实。Kernel 事件、Runtime 阶段和最终 RunManifest 共同形成可重放证据流。

## 3. Web API

兼容的 `/api/chat`、`/api/demo` 和旧 artifact 路由保持不变。V2 使用独立路由：

```text
POST /api/v2/sessions
POST /api/v2/sessions/{id}/turns
GET  /api/v2/sessions/{id}
GET  /api/v2/sessions/{id}/events?after=<sequence>
POST /api/v2/sessions/{id}/pause
POST /api/v2/sessions/{id}/resume
POST /api/v2/sessions/{id}/cancel
GET  /api/v2/sessions/{id}/artifacts/{artifact_id}
```

SSE 可用 `after` 从已确认序号继续读取。下载只接受会话 manifest 中已记录的 artifact ID，并在有
SHA-256 时复验文件；不能把 URL 参数解释为任意文件路径。

暂停是协作式的：请求先显示 `pause_requested`，只有到达事件/动作安全点才显示 `paused`。正在
阻塞的 COMSOL 调用不会被伪装成已暂停。取消先显示 `cancelling`；Runtime 的
`termination_confirmed` 决定能否声称底层执行已终止。

## 4. CLI

原 `comsol-agent` 入口保持兼容。V2 共享事件适配器使用：

```bash
comsol-agent-v2 "<完整圆柱滚子轴承需求>"
comsol-agent-v2 --plan-only "<需求>"
```

CLI 将规格、检索、计划、工具、A-D、修复、预算、审计和 artifact 逐事件渲染，结束时单独列出
四个 Gate。运行时 `Ctrl-C` 请求取消；支持 SIGTSTP 的终端用 `Ctrl-Z` 在下一个安全点切换暂停/
恢复，而不是宣称立即中断 COMSOL。

## 5. 多轮与恢复

同一 V2 session 的新 turn 继承上一轮已验证的类型化规格和 B checkpoint。Planner 仍以权威
ChangeSet 决定参数覆盖或确定性重建；参数覆盖必须重新执行 C/D。历史事件保留 turn ID，新一轮
Gate 从 pending 开始，旧轮求解/审计不能冒充新参数结果。

## 6. 验证

普通回归使用注入式 fake driver，覆盖 API/SSE、状态投影、暂停/恢复、取消、失败分类、已执行
修复、预算、artifact 哈希下载和多轮继承。真实 gate：

```bash
.venv/bin/python scripts/run_v2_m8_web_gate.py --cores 1 --timeout-seconds 1800
```

该命令显式调用真实 LLM、Kernel、固定 Registry、M5 Runtime、COMSOL 6.2 和严格 Auditor；每次
生成新 session、模型与 artifact 目录。只有 A-D 独立通过且存在本次 material artifact 时返回成功。

验证边界需要明确：上述真实 gate 直接驱动 `V2SessionManager`，验证 Agent 到 COMSOL 的真实执行链；
HTTP/SSE 传输层由 fake driver 功能测试覆盖。M8 不声明已验证“真实浏览器→HTTP→SSE→真实
Agent”组合链；该 smoke gate 作为 M9 首项。会话和事件当前仅在内存中，服务重启后不支持恢复或
SSE replay；跨重启恢复需要 M9 持久化设计。
