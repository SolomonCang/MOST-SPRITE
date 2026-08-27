# CADC ESPaDOnS 回归

外部基线由 `tests/data-manifests/cadc-espadons-ad-leo-v1.yaml` 冻结。下载必须显式指定仓库外缓存：

```bash
SPRITE_TESTDATA_DIR=/external/cache make fetch-cadc
```

下载器只接受 manifest 中的 CADC 官方 HTTPS 直取地址，支持断点续传，完成后逐文件核对字节数和 MD5，并在内容寻址目录旁生成 receipt。校验失败的临时文件会被保留为 `.invalid-*`，不会静默刷新冻结值。

`tests/adapters/espadons.py` 是唯一允许解释 ESPaDOnS `o/i/p` 语义的位置。它把 Q/V 保持正号、U 乘以 -1 的参考约定写入 provenance；生产代码不导入该适配器。

完整数值门槛从外部候选结果目录读取标准化 `.npz` 比较包：

- `l2/<raw_product_id>.npz`：`candidate_wavelength_nm`、`reference_wavelength_nm`、`candidate_flux`、`reference_flux`、`continuum_mask`；
- `l3/Q|U|V.npz`：候选与参考的 `polarization/null1/null2`、`reference_uncertainty` 和 `mask`。

运行时同时设置 `SPRITE_CADC_CANDIDATE_DIR`。回归检查波长中位偏差 `<0.1` 分辨单元、连续谱稳健 RMS `<3%`，以及 P/N1/N2 归一化残差中位数 `<=1.5`、99 分位 `<=5`。比较包必须由待验代码、冻结参数与 manifest 生成；不得把参考产品复制为候选。
