# GAMSE 到 MOST-SPRITE 的源码映射

基线固定为 `wangleon/gamse@4d91ead6d8380b75a5a445c2dae78429bc23e0c9`。迁入采用逐函数人工重写；上游仅作为只读算法参考，不复制其包结构、命令行、目录扫描、交互绘图或仪器全局状态。

| GAMSE 来源职责 | SPRITE 稳定接口 | 主要改造 |
| --- | --- | --- |
| `imageproc.combine_images`、`_combine_clipdata` | `combine_calibration(frames, detector_model)` | 不可变输入；内存有界逐行块稳健裁剪；显式 `VAR/DQ/unit/config_version/provenance` |
| `trace.find_apertures`、`ApertureSet` | `trace_orders(master_flat, geometry)` | 返回 SPRITE `TraceModel`；无图形与文件副作用 |
| `flat.get_fiber_flat*` | `build_flat_model(master_flat, trace)` | 显式响应、blaze、方差和坏点质量位 |
| `background.get_interorder_background` | `estimate_background(frame, trace)` | 确定性级次间背景与模型方差；不查目录或数据库 |
| `extract.extract_aperset*` | `extract_channels(l1_frame, trace, channel_map)` | 只接受命名通道映射；返回 SPRITE `SpectrumSet` |
| `wlcalib.fit_wavelength`、`get_wavelength` | `solve_wavelength(calibration_spectra, line_list)` | 显式谱线关联、逐级次解、残差与波长类型 |
| `pipelines.espadons.trace`、`echelle.extract` | `trace_espadons_orders(...)`、`build_spatial_profile(...)`、`extract_espadons_beams(...)` | 保留六峰 slicer 的中心谷与 A/B 约定；输出按 `O_BEAM/E_BEAM + order` 索引的方差/DQ 感知最优抽取 |
| `pipelines.espadons.framesteps.correct_overscan`、`pipelines.espadons.__init__` | `ESPaDOnSAdapter.inspect/canonical_image/preprocess` | FITS 头和 section 为权威；支持空 PRIMARY/HDU1 `.fits.fz`、双放大器、增益/读噪、轴变换；只接受 OLAPA |
| `echelle.wlcalib`、`data/calib/wlcalib_espadons.dat`、固定灯谱 `2495167c` | `solve_espadons_wavelength(...)` | 固定灯谱的二次系数只用于同夜 ThAr 谱线识别；发布系数全部由当前标定重新拟合，并要求双束一致、至少 200 条线覆盖 30 个级次。灯谱 URI、MD5 和 SHA-256 被锁定，但运行时不下载 |
| `data/linelist/thorium.dat`、`data/linelist/argon.dat` | `instruments/data/thar_espadons_air.csv` | 冻结为确定性空气波长/强度子集；文件哈希进入来源清单与科学代码身份 |
| GAMSE aperture/extraction 数据职责 | `CalibrationFrame`、`TraceModel`、`SpectrumChannel`、`SpectrumSet` | 原生 SPRITE 类型；显式 beam/order、单位、方差、短程协方差、DQ、配置版本与 provenance，不暴露 GAMSE 类型 |

附加的 `apply_wavelength_solution(...)`、`resample_common_grid(...)`、偏振解调、级次合并和日心坐标变换属于 SPRITE 原生实现。公共网格函数在 provenance 中强制记录重采样次数，并拒绝第二次插值。

清单中的 `upstream_additional` 保存一个本地文件对应多个上游职责时的附加来源与哈希；`upstream_assets` 保存不可变参考资产的受限 HTTPS URI、MD5、SHA-256 和用途。CI 同时检查目标哈希、来源/资产字段格式、目标唯一性，以及所有声明上述固定 GAMSE commit 的 echelle、instrument、wavelength 运行时代码是否已进入清单。

本地维护责任归属 MOST-SPRITE pipeline 维护组。更新上游基线时必须新建或更新 manifest，人工复核函数差异，并通过合成信号与 CADC golden 回归；不得自动覆盖本地实现。
