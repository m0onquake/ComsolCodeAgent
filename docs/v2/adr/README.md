# Architecture Decision Records

本目录记录 V2 中影响多个模块、难以无损回退或需要长期保持一致的架构决策。

## 使用规则

- 文件名格式：`NNNN-short-title.md`。
- 状态使用 `Proposed`、`Accepted`、`Superseded` 或 `Deprecated`。
- 一个 ADR 只处理一个核心决策。
- 已接受的 ADR 不直接改写结论；需要变更时新增 ADR，并在旧记录中标注替代关系。
- 实现代码和开发文档若与已接受 ADR 冲突，应先更新决策记录或明确说明例外。

## 索引

| 编号 | 决策 | 状态 |
| --- | --- | --- |
| [0001](0001-extension-first-agent-kernel.md) | 采用扩展优先的领域无关 Agent Kernel | Accepted |

## 新建模板

复制 [TEMPLATE.md](TEMPLATE.md)，补齐上下文、决策、后果和验证方式。决策内容应尽量可通过接口约束或测试验证，而不只表达偏好。
