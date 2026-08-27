# 公共接口与产品契约

## HTTP 与事件

所有有副作用的 HTTP API 要求 `Idempotency-Key`，正常接收返回 `202` 和 `command_id` 或
`processing_run_id`。错误统一为 `code/message/details/correlation_id/retryable`。核心 API 包括：

- 序列验证、创建、开始、暂停、恢复、终止及序列/曝光查询；
- 命令状态、仪器快照、处理运行及任务查询；
- 产品、预览、QC、血缘、标定查询与标定注册；
- `/ws/v1/state?cursor=N` 可恢复事件流。

事件至少包含 `raw_file.committed.v1`、`sequence.state.changed.v1`、
`device.state.changed.v1`、`processing_run.state.changed.v1` 与 `alarm.raised.v1`。事件消费者以
`event_id + consumer` 去重。JSON Schema 位于 `schemas/api/` 与 `schemas/events/`。

## FITS

- L0：二维 PRIMARY 图像，`TELEMETRY` 与 `PROVENANCE`；包含模式、序列/组/曝光/命令/配置
  ID、实测和命令角度、通道映射、UTC 时间、软件版本及 FITS 校验和。
- L1：`SCI/VAR/DQ` 图像扩展。
- L2：每个通道为独立二进制表，`CHANNEL_ROLE` 标识 O/E 光束或 TARGET/SKY/DISABLED；列为
  `ORDER/PIXEL/WAVE/FLUX/VAR/DQ`。
- 偏振 L3：`WAVE/I/P/N1/N2`、四个误差列、三项协方差、差分交叉检查和 `DQ`，另含四子曝光
  序列表及来源。
- NONPOL L3：`WAVE/TARGET/SKY/ALPHA/I`、分项误差和 `DQ`；天空无效时 I 等于降级目标谱并
  设置 `SKY_INVALID`，绝不创建偏振占位列。

FITS Schema 位于 `schemas/fits/`。所有级别携带单位、配置 ID、软件版本、QC 标志与数据库血缘；
科学处理身份由输入、标定、参数和代码四个哈希联合确定。
