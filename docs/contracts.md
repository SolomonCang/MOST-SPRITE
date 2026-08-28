# 公共接口与产品契约

## HTTP、权限与幂等

所有有副作用的接口要求 8–128 字符的 `Idempotency-Key`，接收后返回 `202`。相同用户、接口作用域、键和请求体会返回同一资源；同一键配不同请求体返回 `409`，不会创建第二份科学对象。错误统一为：

```json
{
  "code": "CALIBRATION_MISSING",
  "message": "human-readable summary",
  "details": {},
  "correlation_id": "request-correlation-id",
  "retryable": false
}
```

`data_reducer` 可以检查与导入目录、构建标定并启动处理；`administrator` 批准整个 `CalibrationSet`、接受 WARNING 理由并发布或撤回 L3。所有已登录角色可以读取状态、QC、预览、血缘和授权下载。开发模式由 `GET /api/v1/auth/configuration` 提供预置账户，`POST /api/v1/auth/login` 选择账户并签发 HttpOnly 会话 Cookie，`POST /api/v1/auth/logout` 清除会话；签名密钥只从服务端 `SPRITE_LOCAL_AUTH_SECRET` 读取。身份请求头默认禁用。生产模式只接受已配置的 OIDC 身份，且不暴露本机账户登录流程。

## ESPaDOnS 导入与处理接口

| 接口 | 请求要点 | 返回与约束 |
| --- | --- | --- |
| `POST /api/v1/import-inspections` | `root_id`、`relative_path`、`instrument=ESPADONS` | 持久化文件清单、SHA-256 manifest、FITS 分类、Q/U/V 四曝光分组、标定完整性和警告 |
| `GET /api/v1/import-inspections[/{id}]` | 无副作用 | 检查状态及冻结 manifest；列表按最近 100 条返回 |
| `POST /api/v1/imports` | `inspection_id`、检查返回的 `manifest_sha256` | 复制原始字节到受管存储，复核大小/哈希后原子提交；返回批次和序列 ID |
| `GET /api/v1/imports[/{id}]` | 无副作用 | 导入状态、错误和生成的 Q/U/V 序列 |
| `POST /api/v1/calibration-runs` | `import_batch_id`、`parameter_version` | 异步构建版本化 `CalibrationSet`；缺同夜同探测器同读出标定时进入 `WAITING_CALIBRATION` |
| `GET /api/v1/calibration-runs[/{id}]` | 无副作用 | 进度、状态和明确错误码 |
| `GET /api/v1/calibration-sets[/{id}]` | 无副作用 | master bias/flat、双束寻迹/轮廓、FP 几何、ThAr 波长解的总哈希、QC 和警告 |
| `POST /api/v1/calibration-sets/{id}/approve` | `reason`、`accept_warnings` | 仅管理员；QC FAIL 不可批准，WARNING 必须显式接受 |
| `POST /api/v1/processing-runs` | `sequence_id`、`calibration_set_id`、`parameter_version`、`parameters` | 返回 `processing_run_id/status`；真实 ESPaDOnS 必须使用已批准且非 FAIL 的匹配标定 |
| `GET /api/v1/processing-runs[/{id}]` | 无副作用 | 输入、标定、参数、代码四类哈希及进度；`/{id}/tasks` 返回逐任务指标 |
| `GET /api/v1/products/{id}/download` | 已登录身份 | 从受管数据根流式返回文件；响应和产品 JSON 都不暴露服务器 URI |
| `POST /api/v1/products/{id}:publish` | 可选 `reason` | 仅管理员和 L3；未审批标定、FAIL、无理由 WARNING、模拟产品均被拒绝 |

服务端只解析 `SPRITE_IMPORT_ROOTS` 的命名白名单。客户端不能提交绝对路径；目录穿越、逃逸根目录的符号链接、非普通文件、检查与提交之间发生的大小/时间/哈希变化都会被拒绝。检查以 FITS 头为权威、文件名为提示；空 PRIMARY、HDU1 压缩图像是受支持的 ESPaDOnS 原始格式。首版只接受 `DETECTOR=OLAPA`，EEV1 返回 `UNSUPPORTED_DETECTOR`。

关键错误码包括 `SOURCE_CHANGED`、`INCOMPLETE_MODULATION_GROUP`、`UNSUPPORTED_DETECTOR`、`CALIBRATION_MISSING`、`CALIBRATION_NOT_APPROVED`、`PROCESSING_INPUT_INCOMPLETE` 和 `SIMULATION_PUBLICATION_DISABLED`。失败的真实处理不会调用模拟算法。

## 稳定科学接口与身份

`InstrumentAdapter` 负责原始描述、规范化方向、分类/分组、探测器参数和 `DemodulationModel`；`RawDescriptor` 与 `DetectorProfile` 不依赖数据库。`TraceModel`、`WavelengthSolution` 和 L2 光谱始终按“光束角色 + 物理级次”索引。OLAPA 的 Q/V 保持 CFHT 归档符号，U 在发布侧取反；约定版本记录在 `MODVER` 和 provenance。

科学处理身份由不可变输入、`CalibrationSet`、参数快照和代码四类 SHA-256 联合确定。`RawFile` 与 `Product` 保存 instrument、detector profile、source format/import batch 血缘；同一科学身份只产生一组产品。模拟产品永久标记 `SIMULATION_ONLY`，不能转换为真实产品或发布。

## FITS 产品

- L0：原始归档文件保持字节不变，处理只读取另外生成的标准化 L0。标准化二维 PRIMARY 使用内部“交叉色散 × 色散”方向，记录原 HDU、`DATASEC/BIASSEC`、分放大器 overscan/gain/read-noise、裁剪/转置/翻转和源 SHA-256；另含 `TELEMETRY` 与 `PROVENANCE`。
- L1：`SCI/VAR/DQ` 二维扩展；完成 bias/gain、flat、坏点、饱和和宇宙线处理，并传播方差与 DQ。
- L2：O/E 光束分别保存为二进制表，`CHANNEL_ROLE=O_BEAM/E_BEAM`；列为 `ORDER/PIXEL/WAVE/FLUX/VAR/DQ`，可带 `COV_LAG1`。保持每级次原生像素、空气波长、`SPECSYS=TOPOCENT` 和 `RESAMPN=0`，不得在 L2 公共网格重采样。
- 偏振 L3：唯一 1.8 km/s 对数空气波长网格；每个 L2 输入只做一次守恒重采样，然后按逆方差与 blaze 合并重叠级次。`SPECTRUM` 保存 `WAVE/I/P/N1/N2/ERR_I/ERR_P/ERR_N1/ERR_N2/COV_P_N1/COV_P_N2/COV_N1_N2/DIFFCHECK/DQ`；`RESAMPLE_COVARIANCE` 保存 I/P/N1/N2 的相邻像素短程协方差。
- 每个 Q/U/V 序列产生 `UNNORMALIZED|NORMALIZED × TOPOCENT|HELIOCEN` 四个不可变 L3。日心版本只变换波长坐标，不再次插值；归一化只改变 I，P/N1/N2 保持偏振比值。
- L3 主头明确包含 `INSTRUME=ESPADONS`、`DETECTOR=OLAPA`、`STOKES`、`WAVETYPE=AIR`、`SPECSYS`、`NORMSTAT`、`POLCONT=UNSUPPORTED`、`CALSETID`、`MODVER` 和 QC。首版只保证谱线偏振，不声明绝对连续谱偏振精度。

FITS Schema 位于 [`schemas/fits/`](../schemas/fits/)。事件和 WebSocket 继续遵循 `schemas/events/`：至少包含 `raw_file.committed.v1`、`sequence.state.changed.v1`、`processing_run.state.changed.v1` 和 `alarm.raised.v1`，`/ws/v1/state?cursor=N` 可恢复断开的事件流。
