# 模拟栈运行手册

## 启动与健康

在仓库根目录执行 `docker compose up --build`，然后访问 `http://localhost:8080`。API 健康检查
为 `/healthz`，容器级健康状态可通过 `docker compose ps` 查看。首次启动会创建 PostgreSQL、
Redis 和数据具名卷，并加载 `UNVERIFIED` 的 `simulation-v1` 配置快照。

开发栈从本机环境读取 `SPRITE_LOCAL_AUTH_SECRET`，首次打开默认登录 `administrator` 超级管理员。
右上角账户菜单可切换 `observer`、`instrument-engineer`、`data-reducer` 或退出登录；不需要输入账号
密码，密钥也不会进入浏览器。后端仍对每个写操作独立校验角色、`Idempotency-Key` 并追加审计记录。

## 观测流程

1. 在 `/observe` 填写目标，选择 `POL_Q` 或 `NONPOL`，等待预检通过。
2. 创建并开始序列。POL_Q 显示四个配置快照驱动的 FR 位置；NONPOL 显示
   `TARGET/SKY/DISABLED` 角色。
3. 只有 FITS schema、`CHECKSUM`、`DATASUM`、文件和目录 `fsync` 以及原子重命名全部成功后，
   曝光才变为 `COMMITTED`。
4. 在 `/data` 查看 L0–L3、处理运行、光谱、QC 原因和不可变输入血缘。

序列可暂停、恢复或终止。失败后必须先清除故障；若仪器进入 `SAFE_FAULT`，还需要
`instrument_engineer` 调用受审计的恢复接口，然后才能恢复序列。已提交曝光不会被覆盖，恢复
只补做缺失曝光。

## 故障与恢复原则

仅在 `SPRITE_APP_ENV=simulation` 时提供 `/sim/v1/faults/{fault_type}`。模拟器支持状态陈旧、
位置超时、硬限位、导星失锁、CCD 读出、存储满、通信和联锁等故障。故障路径必须满足：

- 未完成原子边界时不创建 RawFile，不增加完成帧数，也不报告 L0 成功；
- 已完成文件提交但数据库不可用时保留已验证 FITS；`sprite-acquisition` 恢复扫描器补登记
  RawFile、L0 产品和 outbox，但不会把失败序列擅自改为成功；
- Redis 不可用时 outbox 保持未发布；恢复后按 `event_id` 去重投递；
- worker 重启以处理身份哈希、带超时的任务 claim 和产品哈希去重，不覆盖文件、不生成重复产品；
- 设备代理在空闲态重启时，控制循环自动执行 `OFFLINE → INITIALIZING` 对账；若重启发生在活动态，
  仍进入 `SAFE_FAULT` 并要求工程师明确恢复。

`docker compose down` 只停止服务。删除具名卷会永久移除数据库、队列和模拟数据，应仅在明确
不再需要这些数据时由操作者单独执行。

## 生产拒绝启动条件

生产模式必须同时设置 `SPRITE_AUTH_MODE=oidc`、`SPRITE_OIDC_ISSUER`、
`SPRITE_OIDC_AUDIENCE`，并设置 `SPRITE_AUTO_CREATE_SCHEMA=false`。任一条件缺失，应用会在启动
阶段拒绝运行。当前仓库不提供正式 OIDC 客户端登录流程，也不得用于真实设备控制或科学发布。
