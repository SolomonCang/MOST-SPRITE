# MOST-SPRITE

MOST-SPRITE 是依据 [`ARCHITECTURE.md`](ARCHITECTURE.md) 建立的光谱偏振处理平台。它同时包含：

- 与真实产品严格隔离、永久不可发布的 MOST 模拟处理链；
- 首个真实仪器适配器 `ESPADONS/OLAPA`，可从服务器挂载目录安全导入 CFHT 原始
  `.fits.fz`、构建同夜标定，并把四次 Q/U/V 曝光处理为 L0、二维 L1、双光束逐级次 L2
  和四种不可变 L3；
- 数据页、QC、血缘、授权下载、标定审批和发布门禁所需的后端契约。

真实 ESPaDOnS 产品不会在标定未审批、科学 QC 失败或 WARNING 未记录接受理由时发布；真实
处理失败也不会回退到模拟算法。

## 一条命令启动

需要 Docker Compose：

```bash
docker compose up --build
```

打开 `http://localhost:8080`。API、OpenAPI 和健康检查分别位于
`http://localhost:8000`、`http://localhost:8000/docs` 和
`http://localhost:8000/healthz`。Compose 明确使用开发观察员身份；不会连接任何真实设备。

栈中包含 `sprite-web`、`sprite-api`、`sprite-control`、`sprite-device-agent-sim`、
`sprite-acquisition`、`sprite-quicklook`、`sprite-scheduler` 和 `sprite-worker`，以及 PostgreSQL 与
Redis。数据、数据库和队列均使用具名卷，普通的 `docker compose down` 不会删除它们。
服务器目录导入还需通过 `SPRITE_IMPORT_ROOTS` 显式配置命名白名单，例如
`{"cadc":"/srv/cadc"}`；浏览器只提交 `root_id` 和相对路径。

## 本地开发与验证

需要 Python 3.12、`uv`、Node 24 和 `pnpm` 11.8：

```bash
make install
make lint
make test
make test-e2e
make smoke-4k
```

`make dev` 以 SQLite、进程内模拟设备和内嵌 worker 启动 API；前端可在另一个终端执行
`cd frontend && pnpm dev`。开发请求使用显式的 `X-SPRITE-User` 与 `X-SPRITE-Role`。生产模式
只有在 OIDC issuer、audience 已配置且关闭自动建表时才允许启动。

## 数据与安全边界

- L0 使用 `.part → FITS/校验和验证 → fsync → 原子重命名`，随后才登记数据库与 outbox。
- L1 是 `SCI/VAR/DQ`；真实 ESPaDOnS L2 按 `O_BEAM/E_BEAM + 物理级次` 保存原生像素与
  空气波长，不重采样。偏振 L3 只在这里建立一次 1.8 km/s 公共网格并保存
  `I/P/N1/N2/误差/协方差/DQ`；NONPOL L3 保存 `TARGET/SKY/ALPHA/I`。
- 探测器、光纤、FR、波长及 QC 参数来自 `configs/` 的版本化快照，状态为 `UNVERIFIED`。
- 模拟产品始终标记 `SIMULATION_ONLY` 且不可发布。真实 ESPaDOnS 产品使用独立血缘和发布
  门禁；L4、绝对连续谱偏振、远端归档、真实设备 SDK 与现场 commissioning 不在当前范围内。
- 迁入算法没有 GAMSE 运行时依赖。固定来源、Apache-2.0 许可证、源码映射和哈希清单位于
  [`third_party/`](third_party/) 与 [`docs/gamse-source-map.md`](docs/gamse-source-map.md)。

冻结的 AD Leo、HR 5501 和 HD 236928 公开数据可以从空数据库执行完整科学回归；下载、重放和
门槛定义见 [`docs/science-validation/cadc-regression.md`](docs/science-validation/cadc-regression.md)。

详细运行说明见 [`docs/operations/simulation-runbook.md`](docs/operations/simulation-runbook.md)，
接口和产品契约见 [`docs/contracts.md`](docs/contracts.md)，CADC 回归说明见
[`docs/science-validation/cadc-regression.md`](docs/science-validation/cadc-regression.md)，前端中英文语言
系统约定见 [`docs/frontend-language-system.md`](docs/frontend-language-system.md)。
