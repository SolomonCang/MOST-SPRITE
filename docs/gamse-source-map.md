# GAMSE 到 MOST-SPRITE 的源码映射

基线固定为 `wangleon/gamse@4d91ead6d8380b75a5a445c2dae78429bc23e0c9`。迁入采用逐函数人工重写；上游仅作为只读算法参考，不复制其包结构、命令行、目录扫描、交互绘图或仪器全局状态。

| GAMSE 来源职责 | SPRITE 稳定接口 | 主要改造 |
| --- | --- | --- |
| `imageproc.combine_images`、`_combine_clipdata` | `combine_calibration(frames, detector_model)` | 不可变输入；稳健裁剪；显式 `VAR/DQ/unit/config_version/provenance` |
| `trace.find_apertures`、`ApertureSet` | `trace_orders(master_flat, geometry)` | 返回 SPRITE `TraceModel`；无图形与文件副作用 |
| `flat.get_fiber_flat*` | `build_flat_model(master_flat, trace)` | 显式响应、blaze、方差和坏点质量位 |
| `background.get_interorder_background` | `estimate_background(frame, trace)` | 确定性级次间背景与模型方差；不查目录或数据库 |
| `extract.extract_aperset*` | `extract_channels(l1_frame, trace, channel_map)` | 只接受命名通道映射；返回 SPRITE `SpectrumSet` |
| `wlcalib.fit_wavelength`、`get_wavelength` | `solve_wavelength(calibration_spectra, line_list)` | 显式谱线关联、逐级次解、残差与波长类型 |

附加的 `apply_wavelength_solution(...)` 和 `resample_common_grid(...)` 属于 SPRITE 原生实现。后者在 provenance 中强制记录重采样次数，并拒绝第二次公共网格插值。

本地维护责任归属 MOST-SPRITE pipeline 维护组。更新上游基线时必须新建或更新 manifest，人工复核函数差异，并通过合成信号与 CADC golden 回归；不得自动覆盖本地实现。
