# ADR 0003: 工作区、Shell 策略沙箱与代码迭代回滚边界

- 状态：Accepted
- 日期：2026-08-20
- 决策者：项目维护者
- 替代：无
- 被替代：无

## 上下文

M3 需要让 V2 搜索和修改代码、执行 pytest/Ruff，并根据真实失败做有限修复。文件路径、命令、
测试输出和 rollback 若只靠调用方约定，会允许越界写入、shell 注入、失控子进程、无证据修复或
失败后留下半完成修改。另一方面，跨平台 Python 进程本身不能把同一用户权限下的恶意程序安全地
降权为真正的 OS 隔离；把 allowlist subprocess 描述成可执行不可信代码的容器会给出错误保证。

## 候选方案

1. 直接开放 `Path` 和 `subprocess(..., shell=True)`，由 prompt 约束路径和命令。
2. 在当前进程提供工作区与命令策略沙箱：严格路径、精确补丁、executable/argv 双 allowlist、
   受控环境、进程组超时/取消、结构化测试证据和文件检查点；明确它只执行可信开发命令。
3. M3 立即依赖特定平台的容器、虚拟机或系统 sandbox，并允许执行任意不可信生成程序。

## 决策

采用方案 2，并为以后需要运行不可信代码时保留升级到方案 3 的边界。

- 文件工具只接受相对于单一 resolved workspace root 的路径。拒绝绝对路径、`..`、符号链接组件、
  非 UTF-8/二进制输入和超预算文件。
- 修改合同是一个或多个 exact replacement，每项声明期望命中次数。命中数量不同即
  `patch_conflict`，不采用模糊定位。多文件写入使用临时文件原子替换，异常时恢复内部检查点。
- Code iteration 在每个候选补丁之前另建文件检查点；失败、取消、非可修复 Observation、预算
  耗尽或相同失败指纹再次出现时逆序恢复。修复补丁必须引用触发它的 Observation ID。
- Shell 不解释字符串命令。宿主同时配置 resolved executable allowlist 和 argv prefix profile；cwd
  由 Workspace 校验，环境变量采用白名单，stdout/stderr 有大小边界，超时/取消终止进程组。
- Python、pytest、Ruff 以及被测仓库代码仍以宿主用户权限运行。因此 M3 Shell Sandbox 是面向可信
  工具和受审查 fixture/工作区代码的策略与生命周期边界，不是恶意代码隔离。未来若 Goal 需要
  执行不可信代码，必须接入容器/VM/系统 sandbox，并通过新的 ADR 固化网络、挂载、资源和平台
  兼容策略。
- pytest 使用 JUnit XML、Ruff 使用 JSON，解析为统一 Observation；自由文本只作为诊断补充，
  不能替代失败类别、测试节点、定位、exit code、artifact 哈希和可重试性。
- 修复内容由 `EvidenceRepairStrategy` 或后续 Repair Rule 扩展提供。通用 loop 只管理证据、预算、
  复验和 rollback，不包含领域或错误字符串分支。

## 后果

正面影响：

- 路径逃逸、符号链接重定向、shell 注入和未批准命令形态在启动动作前被拒绝。
- 测试失败可以被机器读取并直接关联修复，所有成功保留 diff，失败能够恢复原始文件。
- timeout、取消、同错停止和修复预算拥有确定行为，Kernel 与领域实现保持解耦。

成本与风险：

- Exact replacement 要求调用方先读取最新内容；并发编辑会以冲突结束而不是自动合并。
- 文件检查点当前在内存中，只支持单进程运行恢复；跨进程持久恢复需要后续 RunManifest/artifact
  扩展。
- allowlist subprocess 不能阻止获准程序使用其宿主权限。可信命令的选择和 argv profile 仍是
  宿主安全责任。

## 验证

- 单元测试覆盖绝对路径、`..`、符号链接、陈旧补丁、检查点恢复、非 allowlist executable、
  argv profile、超时和执行中取消。
- runner 测试用真实 pytest/Ruff 子进程验证结构化失败、JUnit artifact 哈希和 JSON diagnostics。
- 独立 fixture 仓库测试覆盖搜索与读取、第一次最小补丁、真实测试失败、引用该 Observation 的
  第二次补丁及复验通过。
- 预算耗尽测试证明所有候选修改恢复为运行前内容；M1–M3 联合测试证明 Kernel 不需要领域分支。
