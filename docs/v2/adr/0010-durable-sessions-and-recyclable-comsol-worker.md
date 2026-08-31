# ADR 0010: 持久会话与可回收 COMSOL 子进程 Worker

- 状态：Accepted（真实阻塞 C solve 强取消与取消后资源重建门已通过）
- 日期：2026-08-26
- 决策者：COMSOL Agent V2 maintainers
- 替代：无
- 被替代：无

## 上下文

M8 的 session/event 只在内存中，服务重启后无法 replay；真实 Web gate 也绕过 HTTP 传输。MPh 的
阻塞 Java 调用位于宿主进程线程时，task cancel 不能证明 COMSOL 已终止。M9 要求跨重启证据、真实
HTTP/SSE 组合链，以及能对阻塞 COMSOL 给出可信 termination truth 的生产 Worker。

## 决策

- 每个 session 原子保存一个版本化 JSON，包含严格 snapshot 和连续 append-only events。单文件损坏
  隔离；终态可按 `after` 重播。重启时活动 turn 不自动继续，而是追加
  `SERVICE_RESTART_INTERRUPTED` 并失败。
- session store 是独立证据门。I/O 失败记录 `session_store.degraded`，不得覆盖已经观察到的 runtime
  或 physics 失败；重启 replay 仍会如实暴露未持久化状态。
- 生产轴承 Runtime 使用 spawn 子进程。子进程通过受信任 `module:factory` 创建 MPh Client、固定
  Registry snapshot、执行 catalog 和 Auditor；父进程只发送类型化 backend RPC，不 fork 已启动的
  COMSOL Client，也不开放任意代码 RPC。
- 取消或超时终止并 join/kill 整个子进程后才可设置 `termination_confirmed=true`。旧模型状态不复用；
  后续动作必须创建新进程。无法确认 kill 时 Worker quarantine。
- 父子 Registry versions 必须完全相等；Builder/Path 仍按 ID/version/kind/capability 固定。

## 后果

重启后可审计已完成任务，阻塞调用具有进程级回收边界。成本是子进程启动、RPC 和每个进程单一
COMSOL Client；异常需要序列化远端类型、消息和 traceback。磁盘成为明确生产资源，必须有配额、
保留策略和存储降级指标。

## 验证

- 单元/集成测试覆盖终态重启 replay、活动任务重启失败、损坏/序号隔离、存储失败不覆盖原始失败；
- 进程测试覆盖子进程持有完整模型状态、阻塞调用硬取消、PID 更换与干净重建；
- 真实 HTTP client gate 覆盖 POST、SSE、Agent、COMSOL、持久化与服务重启；
- 2026-08-26 的新鲜 gate 在 C solve 已进入 `running` 后请求取消，C 在 2.686 s 内落为
  `cancelled`，`termination_confirmed=true`，无 solved artifact；随后新 COMSOL lifecycle 1/1 通过。
  完整 JSON 与 SHA-256 见 [M9 验收报告](../M9_ACCEPTANCE_REPORT.md)。
