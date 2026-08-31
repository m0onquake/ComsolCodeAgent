# M9 全量验收报告

## 1. 结论

状态：`in_progress / not complete`（2026-08-28）。

最终非 COMSOL 回归 420/420 通过；本次全新的生产 HTTP→SSE→Agent→进程 Worker→
COMSOL 自然语言链路已通过 A–D 严格审计。另一条独立 12 滚子 10.1 N 直连 gate
也已通过，101 N checkpoint 复用的 COMSOL C/D 和物理审计通过，但会话最终因累计时间预算失败。
15° 变体真实求解完成，但外圈接触平衡审计失败；其余物理矩阵仍在进行。
因此 Definition of Done 仍不满足，未晋升 verified memory。

## 2. 本次可复核证据

| 证据 | 结果 | SHA-256 |
|---|---:|---|
| `reports/v2_m9_acceptance/noncomsol-final-UbKT9T/core.xml` | 203 passed | `1a00cad309a5e8c22db660998070a2f4b6b7df3cb471b4922d5ff6472b5643db` |
| `reports/v2_m9_acceptance/noncomsol-final-UbKT9T/bearing_domain.xml` | 14 passed | `016864a8bfa8c17c76802e0a2900762a3e670497b7dac95fec8c2cce975c010c` |
| `reports/v2_m9_acceptance/noncomsol-final-UbKT9T/web.xml` | 13 passed, 1 warning | `23671d0165b5179295fc936de16c4bfed07c007f022f995fa4c7797def517f17` |
| `reports/v2_m9_acceptance/noncomsol-final-UbKT9T/full.xml` | 416 passed, 1 warning | `468353269be7fd01a16ee3674cd7d8f3f8270c65330bbd17417e2c0428c2fe3a` |
| `reports/v2_m9_acceptance/noncomsol-final-UbKT9T/ruff-full.json` | 3,138 errors; gate failed | `aba1993176cea41e4dc36f3f18e463170fe1882cca2f39282b04aaec85dff0c7` |
| `reports/v2_m9_acceptance/smokes/lifecycle.json` | real COMSOL lifecycle passed | `2e8cbcb9df089e7a1f8baea41357c564cae5c725d19fa86e887c013d7800f502` |
| `reports/v2_m9_acceptance/smokes/api_repair.json` | real `INVALID_PROPERTY` repair passed | `64ba34baed15e589e448d851b2aa8a5185d1f9cba9bfcc47f10fd4bcaff33b93` |
| `reports/v2_m9_acceptance/20260826T040535-8b30675d/v2_m9_http_gate.json` | A/B/C passed, D failed, restart replay passed | `9fa3eab92bcb51cfc315c9ec75c3d2cdd0b5aad23d1ceddcd566844fad696999` |
| `reports/v2_m9_cancel_evidence/20260826T044059-cf76ad3c/v2_m9_cancel_gate.json` | real blocking C solve cancel gate 8/8 passed | `2fc33ec5b9ed2aa910430ad4625d4dc144f15b605cd0407778e7c844b1c7676b` |
| `reports/v2_m9_cancel_evidence/20260826T044059-cf76ad3c/post_cancel_lifecycle.json` | post-cancel real COMSOL lifecycle passed | `c49fd656e93903116f5f7ec5d145292aa1639419dc60bf0fa07b57a4f85c9005` |
| `reports/v2_m9_acceptance/noncomsol-final-thRW5j/pytest-junit.xml` | 420 passed, 1 warning | `44516878ced220a37cfab1a2489e921bcd59639e9ef942786ab83472e2ef129f` |
| `reports/v2_m9_acceptance/20260827T072416-384ea1e2/v2_m9_http_gate.json` | fresh production HTTP/SSE A–D strict success | `4c23cb34f1e562e3a4033c754971ccbab9318f8f7473b17943d317e23600e122` |
| `reports/v2_m9_acceptance/physical_matrix/20260827T151314-fa9eff14/v2_m7_audit_evidence.json` | fresh 12-roller 10.1 N strict success | `e9c2937fc53c6f991fcd24796f4e50f9be7aecf2c6e2bd0cb5875e2ed6557231` |
| `reports/v2_m9_acceptance/20260827T072416-384ea1e2/v2_m9_followup_101n.json` | C/D audit passed; final session budget failed | `a01097a00514b961b84cd01351e9f25e61605dae9d580fa07745ebcf12f1d25c` |
| `reports/v2_m9_acceptance/physical_matrix/20260828T120833-a4d3a483/v2_m7_audit_evidence.json` | 15° solved; contact-balance audit failed | `88ae0df2f0bd67310706c6583aa3f35efc6d483754559a6de795c9d91ec8155d` |

证据均由本次命令产生。`docs/v2/evidence/` 和 M7/M8 历史 artifact 仅用于兼容/检索上下文，不计入
本次真实 COMSOL 成功率。

## 3. 指标

| 指标 | 本次值 | 解释 |
|---|---:|---|
| 非 COMSOL 测试成功率 | 420/420 = 100% | 普通回归未配置外部 LLM 凭据；1 个已知弃用 warning |
| 真实 lifecycle | 1/1 = 100% | 不代表 solve/audit |
| 真实 API 修复有效率 | 1/1 = 100% | `INVALID_PROPERTY`→checkpoint→repair→verify |
| 首次 A/B/C 阶段成功率 | 各 1/1 = 100% | 新 HTTP session、新模型、新 checkpoint |
| 严格 D 审计通过率 | 0/1 = 0% | `ENOSPC`，不可计为物理成功 |
| Kernel action / retry / repair | 1 / 0 / 0 | 无同错重复；D 失败不可用无关修复 |
| Kernel elapsed | 1286.452 s | 1 core，约 0.357 core-hour 上界 |
| C solve 时间 | 571.905 s | B passed 到 C passed |
| D 至失败时间 | 698.888 s | 保存/取数阶段耗尽空间 |
| LLM 调用与 token | 2 次，3754 tokens | prompt 3095，completion 659 |
| LLM 金额 | 未知 | provider pricing 未配置，不伪造金额 |
| 检索 Top-k 命中 | 1/1 | 命中兼容 M7 context，Planner 引用 1/1 |
| 检索采用后严格成功 | 0/1 | 最终 D 未通过；误复用率 0/1（同 family/版本/拓扑） |
| 全模型 LLM 重写 | 0 | 路由为 deterministic rebuild |
| HTTP/SSE 连续性 | 20/20 连续 | 独立 HTTP client 观测 |
| 服务重启恢复 | snapshot 相等，尾部 3/3 replay | 失败 session 也可复播 |
| 真实阻塞 solve 取消 | 8/8 checks = 100% | 在 C running 后取消，`termination_confirmed=true` |
| C 取消确认时间 | 2.686 s | C `started_at`→`finished_at`；取消延迟设置为 2 s |
| 取消后资源可用性 | 1/1 = 100% | 新 COMSOL lifecycle 成功，19,952-byte artifact |
| 取消 gate LLM 调用 | 2 次，3802 tokens | prompt 3092，completion 710；金额未知 |
| 全仓 Ruff | 0/1 = 0% | 3,138 errors；M9 修改范围 Ruff 1/1 通过 |
| 生产自然语言严格 E2E | 1/1 = 100% | 12 滚子、10.1 N、A–D、重启恢复与 SSE replay 通过 |
| 独立基准物理 gate | 1/1 = 100% | 628.17 s，0 solve retry，4/4 V2 auditor 通过 |
| 101 N checkpoint 复用 | 物理 1/1，会话 0/1 | A/B skipped，C/D passed；累计 3895.31 s 超过 2400 s budget |
| 15° 物理 gate | 0/1 | 1335.59 s；外圈接触 9.8097336 N，目标 10.1 N |

LLM 的 request ID、provider、model 和 usage 位于 gate JSON；API key 未落盘。成本缺少配置时明确
标为 unknown，而不是用 token 推测账单。

## 4. 未通过项

1. 101 N 的 COMSOL 和物理审计通过，但最终 session 因累计 elapsed-time budget 失败；
   未达成完整会话 Definition of Done。
2. 15° 例的外圈接触力平衡未通过；+Y/-X/-Y、合法尺寸和数量变化仍在执行/
   待执行，不得用基准模型代替。
3. 非收敛真实 solver strategy 尚未在本次 M9 运行。
4. 全仓 `.venv/bin/ruff check comsol_agent tests scripts` 报告 3,138 个错误；它们横跨大量非 M9
   文件，本次不批量改写用户工作树。M9 改动范围 Ruff 通过，已满足第 5 节里程碑门；
   全仓结果作为既有技术债披露，不单独冒充 M9 失败原因。
5. 由于上述未通过，发布状态仍是 release candidate，ROADMAP M9 不得改为 complete。

## 5. 复现命令

```bash
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u ANTHROPIC_API_KEY \
  .venv/bin/python -m pytest -q

.venv/bin/ruff check comsol_agent tests scripts

.venv/bin/python scripts/run_v2_comsol_smoke.py \
  --version 6.2 --cores 1 \
  --evidence-path reports/v2_m9_acceptance/smokes/lifecycle.json

.venv/bin/python scripts/run_v2_repair_smoke.py \
  --version 6.2 --cores 1 \
  --evidence-path reports/v2_m9_acceptance/smokes/api_repair.json

.venv/bin/python scripts/run_v2_m9_http_gate.py \
  --cores 1 --timeout-seconds 2400

.venv/bin/python scripts/run_v2_m9_cancel_gate.py \
  --cores 1 --timeout-seconds 2400 --cancel-delay-seconds 2
```

重跑最后一条前至少准备 2 GiB 可用空间。必须保留新的 session/model/Run ID；不得把当前失败目录
或 M7/M8 solved MPH 复制到新目录冒充成功。
