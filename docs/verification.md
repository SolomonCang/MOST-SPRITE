# 验证矩阵

`make verify` 执行静态检查、类型检查、GAMSE 来源哈希检查、普通单元/属性/集成测试、前端组件
测试、生产构建、Playwright 垂直切片以及 Compose 配置校验。

普通 CI 使用缩小的固定种子合成数据；`make smoke-4k` 至少执行一次 4096×4096 L0 原子提交与
FITS 校验。CI 还会构建 API 和 Web 容器，拒绝任何 `import gamse`。

`.github/workflows/cadc-regression.yml` 是缓存化的手动/每周任务。CADC 文件只下载到 runner 的
外部缓存并逐项校验大小和 MD5。冻结参考元数据始终验证；数值候选包通过受控变量提供时，执行
波长、连续谱以及 P/N1/N2 的门槛比较。该结果仅为回归测试，不替代 MOST commissioning。

## 2026-08-26 基线验收记录

| 检查项 | 结果 |
| --- | --- |
| Python 单元、属性、契约与集成测试 | 48 passed；4 个需要外部 CADC 缓存/候选包的 golden test 按设计 skipped |
| Python 规范与类型 | Ruff 通过；Mypy 对 69 个源码文件通过 |
| 前端组件测试与构建 | 6 passed；TypeScript 类型检查及 Vite 生产构建通过 |
| Playwright 观察员流程 | POL_Q 与 NONPOL 共 2 条浏览器端到端测试通过 |
| PostgreSQL 迁移 | `0001_initial → 0002_processing_claim` 通过；全新 SQLite 验证库升级及 Alembic drift check 通过 |
| Compose 运行态 | API/Web/PostgreSQL/Redis 健康；控制、采集、快视、调度、Worker 和设备模拟器持续运行且无错误日志 |
| POL_Q 产品唯一性 | 4×L0、4×QUICKLOOK、4×L1、4×L2、1×L3；URI 全部唯一，重复处理请求返回同一 run |
| 完整探测器提交 | 4096×4096 模拟帧完成不可变 L0 写入、FITS schema 与 checksum 验证 |
| GAMSE 隔离 | 固定来源哈希清单通过；运行时代码不存在 `import gamse` |

完整 CADC 数值回归没有在本次本地验收中冒充执行：它需要显式准备的外部缓存和冻结 reduction
候选包。CI 工作流会在这些输入存在时才启用对应门槛测试。
