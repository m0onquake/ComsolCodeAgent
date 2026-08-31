# V2 M9 发布、迁移与回滚说明

## 1. 当前发布状态

当前状态是 **M9 release candidate / not released**。非 COMSOL 套件、持久会话、真实 HTTP/SSE
传输、进程 Worker 和真实阻塞 solve 强取消已有证据；规定的全量 COMSOL/物理矩阵与全仓
Ruff 尚未通过。
因此不得使用 `complete`、生产就绪或扩大 verified bearing envelope 的表述。

## 2. Release candidate 变化

- V2 Web session 和 append-only event 流使用原子 JSON 持久化，终态可在服务重启后 SSE replay；
- 重启时仍活动的 turn 不会伪恢复，而是记录 `SERVICE_RESTART_INTERRUPTED` 并安全失败；
- 生产 V2 轴承 driver 默认使用 spawn 子进程持有 MPh/COMSOL Client；取消或超时终止整个子进程，
  新任务只能由新进程承接；
- 真实 HTTP gate 通过独立客户端验证 POST、SSE、Agent、COMSOL 和重启 replay；
- session store I/O 失败记录为独立 `session_store.degraded`，不覆盖更早的 runtime/physics 失败；
- 旧 `comsol-agent`、`/api/chat` 和 demo/replay 入口保持兼容。

## 3. 配置迁移

部署前显式配置：

```bash
export COMSOL_AGENT_V2_SESSION_DIR=/durable/comsol-agent/v2-sessions
export COMSOL_AGENT_V2_OUTPUT_ROOT=/durable/comsol-agent/v2-runs
export COMSOL_AGENT_COMSOL_VERSION=6.2
export COMSOL_AGENT_COMSOL_CORES=1
export COMSOL_AGENT_V2_TIMEOUT_SECONDS=2400
```

两个目录必须位于有配额监控的持久卷。单个严格轴承运行可能生成两份约 0.5 GB 的 solved MPH，
上线前至少预留“最大并发 × 2 GB”可用空间，并设置运行保留策略。不得在空间不足时删除 verified
证据或把历史 artifact 当成本次新运行。

旧 M8 会话仅存在内存，无法无损迁移。升级后新会话使用 `schema_version=1.0.0` 的单 session JSON；
每个文件包含 snapshot 与从 1 开始连续的 events。损坏文件被隔离，不影响其他 session。旧 checkpoint
仍须通过 runtime、COMSOL、backend、Builder、扩展快照、输入和内容哈希兼容检查，不能批量改版本。

## 4. 上线前检查

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check comsol_agent/v2 tests/test_v2_web.py tests/test_v2_comsol_runtime.py
.venv/bin/python scripts/run_v2_comsol_smoke.py --version 6.2 --cores 1
.venv/bin/python scripts/run_v2_repair_smoke.py --version 6.2 --cores 1
.venv/bin/python scripts/run_v2_m9_http_gate.py --cores 1 --timeout-seconds 2400
.venv/bin/python scripts/run_v2_m9_cancel_gate.py --cores 1 --timeout-seconds 2400 --cancel-delay-seconds 2
```

最后一条是显式付费/耗时 gate，会调用真实 LLM 和 COMSOL。只有 A–D、restart replay、artifact 哈希
和 M9 报告全部通过才可发布。

## 5. 回滚方案

1. 停止接收新的 V2 turn，等待活动 Worker 到安全点；无法等待时调用 cancel，并保存
   `termination_confirmed`。
2. 备份 session store、RunManifest、checkpoint、审计 JSON 和哈希；不要只备份页面快照。
3. 停止 Web 服务，确认 COMSOL 子进程和许可证已释放。
4. 回退应用版本。旧 CLI/API 入口可继续使用，但不得把它们的 demo/replay 状态投影为 V2 Gate。
5. 若仅临时切回进程内 Worker，必须显式记录 `hard_cancel=false`；该配置不满足 M9 生产 DoD，
   不能作为长期发布状态。
6. 恢复前一版本的 session store 备份。新 schema 文件不做就地降级写；保留只读以供审计。
7. 用 lifecycle smoke、一次取消和一次 artifact 下载验证回滚。任何未确认终止的模型进入 quarantine。

回滚不会自动删除新 artifact，也不会自动晋升/降级 memory。需要清理时按精确 Run ID 审核并保留
紧凑证据；禁止对 `reports/`、工作区根或未解析变量做宽泛递归删除。

## 6. 已知阻塞与复现

截至 2026-08-27，本机仅余约 382 MiB；物理 gate 在 D 保存 solved MPH 时失败。复现证据和
命令见 [M9_ACCEPTANCE_REPORT.md](M9_ACCEPTANCE_REPORT.md)。释放足够空间后必须创建新 Run；不得
从失败目录复制历史 solved MPH 补齐。
