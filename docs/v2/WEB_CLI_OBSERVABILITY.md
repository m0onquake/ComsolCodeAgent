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

M9 增加 `JsonSessionStore`：snapshot 与连续 event 流按 session 原子落盘，终态服务重启后支持
`after` SSE replay；活动 turn 在重启时明确失败，不伪装恢复。存储故障记录为独立 degraded 证据，
不覆盖先发生的 runtime/physics 失败。

显式 gate：

```bash
.venv/bin/python scripts/run_v2_m9_http_gate.py --cores 1 --timeout-seconds 2400
```

它启动真实 Uvicorn，用独立 HTTP client 提交需求、消费 SSE、运行 Agent/COMSOL，随后重启服务并
复验 snapshot/replay。2026-08-26 的首次本次运行已证明 HTTP/SSE、A/B/C 和重启 replay，但 D 因
磁盘耗尽失败；详细边界见 [M9_ACCEPTANCE_REPORT.md](M9_ACCEPTANCE_REPORT.md)。

真实强取消 gate 由 `scripts/run_v2_m9_cancel_gate.py` 在 C solve 进入 `running` 后取消，并要求
`termination_confirmed=true`、无 solved artifact 且取消后新 COMSOL lifecycle 通过。2026-08-26 的
新鲜 gate 8/8 checks 通过，证据哈希见 M9 验收报告。
