# 验证矩阵

`make verify` 执行 Python/TypeScript 静态与类型检查、GAMSE 来源哈希检查、普通单元/属性/集成测试、前端组件测试、生产构建、Playwright 垂直切片以及 Compose 配置校验。`make smoke-4k` 另行验证 4096×4096 L0 原子提交与 FITS checksum。CI 构建 API/Web 容器并拒绝任何运行时 `import gamse`。

`.github/workflows/cadc-regression.yml` 是缓存化的手动/每周正式科学任务：从 CADC 官方地址校验三份冻结 manifest，分别用空数据库重放 AD Leo、HR 5501 和 HD 236928，独立复跑 HR 5501 证明科学身份可重复，随后构建仅测试用比较包并强制全部发布门槛。工作流不依赖生产产品或外部候选 URI。

## 2026-08-27 发布候选验收记录

| 检查项 | 结果 |
| --- | --- |
| Python 单元、属性、契约与集成测试 | 71 passed；无普通测试跳过 |
| CADC/CFHT golden 回归 | 7 passed：3 项冻结参考/来源检查 + 4 项 L2/L3/标准星门槛 |
| Python 规范与类型 | Ruff 通过；Mypy 对 80 个源码文件通过；GAMSE 双边来源/资产/目标哈希通过 |
| 前端组件测试与构建 | 11 passed；TypeScript 类型检查、lint 和 Vite 生产构建通过 |
| Playwright 流程 | 中英文/主题持久化、POL_Q、NONPOL 共 3 条浏览器端到端测试通过 |
| 数据库迁移 | 全新 SQLite 从 `0001_initial` 增量升级到 `0004_api_idempotency`；Alembic drift check 无新增操作 |
| 导入与发布安全 | 路径穿越/符号链接逃逸、SOURCE_CHANGED、重复提交、授权下载、标定审批、WARNING 理由、模拟发布阻断均通过集成测试 |
| 完整探测器提交 | 4096×4096 模拟帧完成不可变 L0 写入、FITS schema 与 checksum 验证 |
| Compose/容器 | Compose 配置通过；API/Web 镜像由 GitHub CI 构建（本次本机 Docker daemon 未运行） |
| GAMSE 隔离 | 固定 commit、来源文件、OLAPA 灯谱 URI/MD5/SHA-256 和目标哈希通过；运行时代码不存在 `import gamse` 或下载 |

## 最终源码公开数据重放

| 数据集 | CalibrationSet QC | 寻迹 RMS | ThAr RMS | 产品 |
| --- | --- | ---: | ---: | ---: |
| AD Leo Q/U/V | WARNING：10 张 flat 少于推荐数量，必须管理员记录接受理由 | 0.0193 pixel | 111.3 m/s | 48：12 L0、12 L1、12 L2、12 L3 |
| HR 5501 V | PASS | 0.0441 pixel | 89.0 m/s | 16：各级 4 个 |
| HD 236928 Q/U | PASS | 0.0470 pixel | 93.4 m/s | 32：各级 8 个 |

三套数据合计从空数据库生成 96 个标准产品；所有 alignment 有效率约 98.70%。独立 HR 5501 重放的 input/calibration/parameter/code/product 哈希与全部数值 FITS 指纹完全相同。

12 个 AD Leo L2 的波长偏差为 0.0087–0.0152 分辨单元，连续谱稳健 RMS 为 1.03%–1.16%。六个偏振序列的 P/N1/N2 最差归一化残差中位数为 0.735、最差 99 分位为 2.99。HR 5501 伪 V 中位幅度为 `3.41×10⁻⁴`；HD 236928 得到 Q=`−0.06044`、U=`−0.01947`、幅度 6.35%、偏振角 98.93°，冻结目录角为 98.14°。

详细输入、比较规则和可复现命令见 [`science-validation/cadc-regression.md`](science-validation/cadc-regression.md)。这些结果是谱线偏振发布门槛，不是绝对连续谱偏振精度声明，也不替代 MOST 现场 commissioning。
