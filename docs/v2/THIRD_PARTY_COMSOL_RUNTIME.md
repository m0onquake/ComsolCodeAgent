# M5 第三方 COMSOL Runtime 调研与来源

调研日期：2026-08-21。以下 commit 是 M5 设计评估的固定输入；本仓库没有复制这些项目的源代码，
因此没有 vendored 第三方文件。若未来复制或修改代码，必须在目标文件保留上游版权、许可证和
commit 来源。

## 1. MPh

- 仓库：<https://github.com/MPh-py/MPh>
- 固定 commit：`d6efe2a2cad84424b48aec8f0fe03efe60d69289`（2026-08-16，版本 1.3.2）
- 许可证：MIT
- 维护状态：Production/Stable；固定 commit 发布 1.3.2，本机安装 1.3.1
- 兼容性：Python >=3.10；文档称 COMSOL 6.0+ 预期可用并测试至 6.3；1.3.0 起支持 Apple
  Silicon COMSOL；COMSOL 5.5/5.6 需要旧 JPype，非 M5 支持基线
- M5 范围：首选 COMSOL/Java 驱动。`MphBackendAdapter` 复用 start/create/load/save、参数、
  build、mesh、solve、evaluate 和 export，并显式处理每进程单客户端限制

## 2. COMSOL_Multiphysics_MCP

- 仓库：<https://github.com/wjc9011/COMSOL_Multiphysics_MCP>
- 固定 commit：`99172f8f43c6753c2442c406cd5c6055ea8c5bef`（2026-08-12）
- 许可证：MIT
- 维护状态：近期活跃；README 将 integration tests 标为进行中
- 兼容性：Python >=3.10、MPh >=1.3；README 声称 COMSOL 5.x/6.x
- M5 范围：只借鉴 session/model/study/results、模型版本化、MCP schema 和单客户端会话管理的
  职责划分。不复制其完整工具集，不引入 PDF/RAG 依赖，不开放任意 Java/GUI 工具

## 3. cmslh5

- 仓库：<https://github.com/smartgeotechnics/cmslh5>
- 固定 commit：`5583b824b6e5d0744d11bc3a539c72239089f67c`（2026-04-12，项目版本 0.1.6）
- 许可证：MIT
- 维护状态：Beta；固定 commit 为最近维护提交
- 兼容性：Python >=3.9；核心依赖 h5py/numpy/scipy；`.mph` 转换是可选 extra，要求 MPh >=1.2
- M5 范围：仅作为未来 `ArtifactStore`/后处理 adapter 候选。M5 核心不依赖 cmslh5、h5py 或
  scipy，不把其格式作为 checkpoint 真相

## 4. mph-agent

- 仓库：<https://github.com/iammm0/mph-agent>
- 固定 commit：`0660b3486414c3775fd165ef6a07263086e1a217`（2026-08-20）
- 许可证：MIT（README 另含 COMSOL 合法许可声明）
- 维护状态：近期活跃、Alpha；README 展示 1.1.2，`pyproject.toml` 仍为 0.1.0
- 兼容性：Python >=3.10，项目描述面向 COMSOL 6.3，直接依赖 JPype 而非 MPh
- M5 范围：只参考分阶段 `.mph`、操作目录、失败事件和修复闭环。没有复制代码、prompt 或桌面端；
  其开放式 Java fallback 不进入 V2 默认 MCP

## 5. 本仓库既有实现

`comsol_agent/tools/comsol/` 是优先复用的本地来源：

- 实际复用：`COMSOLClient` 单例、`ModelHandle` 和其 start/create/load/save/close/summary 生命周期；
- 通过类型化 adapter 复用的底层 MPh 操作：parameter、build、mesh、solve、evaluate、export；
- 评估但不直接调用：`model_ops.py`、`solve.py`、`evaluate.py` 的 dict 工具，因为它们会折叠异常、
  接受任意输出路径，且旧 `comsol_execute_java` 超出 M5 公开权限边界；
- 没有扩充任何 bearing demo 脚本。
