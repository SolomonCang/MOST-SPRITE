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
bash scripts/start.sh
```

或使用 Make 入口：

```bash
make start
```

打开 `http://localhost:8080`。API、OpenAPI 和健康检查分别位于
`http://localhost:8000`、`http://localhost:8000/docs` 和
`http://localhost:8000/healthz`。当前测试阶段，首次打开会使用预置的本机超级管理员账号，客户端可访问
全部应用工作流；也可从右上角账户菜单切换为观测人员、仪器工程人员或数据处理人员，并可随时登出。
这些账号仅用于开发认证，不会授予宿主机 root 权限，也不会连接任何真实设备。
Compose 默认从仓库同级的
`../MOST-SPRITE-testdata/cadc-cache/cadc-espadons-ad-leo-v1` 只读挂载公开测试数据；如果数据位于
其他位置，可在启动前设置 `SPRITE_CADC_IMPORT_PATH=/absolute/path/to/dataset`。

前端根入口是系统仪表盘：身份、配置、服务健康、审计和界面设置保留在平台层。仪表盘会在独立
标签页打开观测控制台、仪器工程台和数据处理台；三者拥有各自的全屏外壳和权限上下文，不再共享
聚合导航。观测与工程工作区同时显示 WebSocket 过程流，数据工作区独立承载导入、标定、提取和分析。

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
`cd frontend && pnpm dev`。本机开发认证不需要账号密码：后端从
`SPRITE_LOCAL_AUTH_SECRET` 读取至少 32 字符的本机密钥，浏览器只保存后端签发的 HttpOnly 会话，
不会读取或传输密钥。默认预置账号为 `administrator`、`observer`、`instrument-engineer` 和
`data-reducer`；可通过 `SPRITE_LOCAL_AUTH_DEFAULT_USERNAME` 更改首次默认登录账号。旧的身份请求头
默认禁用，仅可用 `SPRITE_ALLOW_LEGACY_DEV_HEADERS=true` 为自动化兼容显式开启。生产模式只有在
OIDC issuer、audience 已配置且关闭自动建表时才允许启动，本机账户选择接口在生产环境不可用。

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
