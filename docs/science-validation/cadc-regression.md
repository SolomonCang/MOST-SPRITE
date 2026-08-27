# CADC ESPaDOnS 科学回归

## 冻结数据与边界

三份 manifest 冻结了 CADC/CFHT 官方直取 URL、文件名、字节数、MD5、观测夜、探测器和读出模式：

- AD Leo：12 张 OLAPA 原始 science，组成完整 Q/U/V；同夜 bias、10 张 flat、ThAr/COMPARISON 与 FP/alignment；对应 12 个 `i` 和 3 个 `p` 参考产品。
- HR 5501：V 序列 `3210588o–3210591o` 和 `3210588p`，同夜 3 张 bias、20 张 flat、ThAr 与 alignment。
- HD 236928（BD+59 389）：Q/U 序列 `3251968o–3251975o`，参考 `3251968p/3251972p`，以及同夜 3 张 bias、20 张 flat、ThAr 与 alignment。

原始 `o` 文件是生产处理的唯一 science 输入；CFHT `i/p` 只在测试适配器中充当外部回归参考，绝不复制为候选结果，也不进入标定或处理链。适配器保持 Q/V 参考符号并对 U 取反，且把来源 raw product ID 写入测试 provenance。

下载必须使用仓库外的绝对缓存目录：

```bash
export SPRITE_TESTDATA_DIR=/absolute/external/cadc-cache
make fetch-cadc
```

下载器只接受 manifest 中的 CADC 官方 HTTPS 地址，支持断点续传，逐文件核对大小和 MD5，并在内容寻址目录旁生成 receipt。校验失败的临时文件保留为 `.invalid-*`，不会静默更新冻结值。

## 从空数据库完整重放

下面的目录都必须位于源码仓库外；每个 replay 工作目录首次运行时必须为空：

```bash
export SPRITE_REPLAY_ROOT=/absolute/external/espadons-replays
export SPRITE_CADC_CANDIDATE_DIR=/absolute/external/cadc-candidate
mkdir -p "$SPRITE_REPLAY_ROOT"

uv run python tools/testdata/run_espadons_replay.py \
  --manifest tests/data-manifests/cadc-espadons-ad-leo-v1.yaml \
  --cache-dir "$SPRITE_TESTDATA_DIR" \
  --work-dir "$SPRITE_REPLAY_ROOT/ad-leo"

uv run python tools/testdata/run_espadons_replay.py \
  --manifest tests/data-manifests/cadc-espadons-hr-5501-v1.yaml \
  --cache-dir "$SPRITE_TESTDATA_DIR" \
  --work-dir "$SPRITE_REPLAY_ROOT/hr-5501"

uv run python tools/testdata/run_espadons_replay.py \
  --manifest tests/data-manifests/cadc-espadons-hd-236928-v1.yaml \
  --cache-dir "$SPRITE_TESTDATA_DIR" \
  --work-dir "$SPRITE_REPLAY_ROOT/hd-236928"

uv run python tools/testdata/build_cadc_candidate.py \
  --cache-dir "$SPRITE_TESTDATA_DIR" \
  --candidate-dir "$SPRITE_CADC_CANDIDATE_DIR" \
  --ad-replay "$SPRITE_REPLAY_ROOT/ad-leo" \
  --hr-replay "$SPRITE_REPLAY_ROOT/hr-5501" \
  --hd-replay "$SPRITE_REPLAY_ROOT/hd-236928"

uv run pytest -q tests/golden/test_cadc_reference.py
uv run pytest -q tests/golden/test_cadc_regression_bundle.py
```

`run_espadons_replay.py` 为每个数据集创建全新数据库和受管存储，执行检查、导入、标定、审批及全部 Q/U/V 处理；`regression-summary.json` 记录 input/calibration/parameter/code/product 哈希及 FITS 数值指纹。用另一空目录重放并传入 `--expected-summary`，可要求这些稳定身份逐项完全相同：

```bash
uv run python tools/testdata/run_espadons_replay.py \
  --manifest tests/data-manifests/cadc-espadons-hr-5501-v1.yaml \
  --cache-dir "$SPRITE_TESTDATA_DIR" \
  --work-dir "$SPRITE_REPLAY_ROOT/hr-5501-repeat" \
  --expected-summary "$SPRITE_REPLAY_ROOT/hr-5501/regression-summary.json"
```

手动及每周 GitHub Actions 会自动执行以上三套重放、HR 5501 确定性复跑、候选包构建和全部门槛；不再依赖外部候选 URI。

## 比较方法与门槛

`tests/adapters/espadons.py` 是唯一解释 CFHT `o/i/p` 产品语义的位置。L2 比较先依据 CFHT `i` 头中的速度把参考空气波长从 HELIOCEN 转回 TOPOCENT，再按负向重置或大于 0.1 nm 的正向跳变拆分 40 个拼接级次。发布指标只使用 AD Leo 信噪比足够的物理级次 m=24..54；每个级次用谱线互相关求唯一速度偏差。为隔离 CFHT blaze/连续谱处理与本项目抽取响应的差异，连续谱 RMS 只在比较包中进行平滑乘性匹配，不修改候选 FITS。

L3 比较把候选与参考的不确定度按平方和合并，并只为谱线结构比较减去 0.5 nm 候选—参考平滑基线；该操作同样只存在于测试包。生产 L3 的 P/N1/N2 不做连续谱偏振消除。

门槛如下：

- L2 波长中位偏差 `<0.1` 分辨单元，连续谱稳健 RMS `<3%`；标定解 RMS 目标 `≤150 m/s`，寻迹 RMS `≤0.1 pixel`。
- L3 每个 P/N1/N2 的归一化残差中位数 `≤1.5`、99 分位 `≤5`。
- HR 5501 每分辨单元伪偏振中位幅度 `≤10⁻³`，N1/N2 与候选噪声一致。
- HD 236928 的 Q/U 符号、3–10% 幅度哨兵和偏振角与 R 波段目录值相差不超过 2°；这是符号/角度回归，不是绝对连续谱偏振精度声明。

## 2026-08-27 本地正式数据基线

| 数据集 | 寻迹 RMS | ThAr RMS | alignment 有效率 | 完整产品 |
| --- | ---: | ---: | ---: | ---: |
| AD Leo Q/U/V | 0.0193 pixel | 111.3 m/s | 98.70% | 12 L0 + 12 L1 + 12 L2 + 12 L3；10 张 flat 触发可审计 WARNING |
| HR 5501 V | 0.0441 pixel | 89.0 m/s | 98.70% | 4 L0 + 4 L1 + 4 L2 + 4 L3，全部 PASS |
| HD 236928 Q/U | 0.0470 pixel | 93.4 m/s | 98.70% | 8 L0 + 8 L1 + 8 L2 + 8 L3，全部 PASS |

12 个 AD Leo L2 候选的波长偏差范围为 0.0087–0.0152 分辨单元，连续谱 RMS 为 1.03%–1.16%。六个 L3 回归包中最差的归一化残差中位数为 0.735，最差 99 分位为 2.99。HR 5501 的 V 中位伪偏振为 `−3.41×10⁻⁴`。HD 236928 得到 Q=`−0.06044`、U=`−0.01947`、幅度 6.35%、偏振角 98.93°，冻结目录角为 98.14°。独立 HR 5501 空数据库复跑的科学身份与全部数值 FITS 指纹完全一致。

这些结果验证谱线偏振处理链；依据 [CFHT ESPaDOnS FAQ](https://www.cfht.hawaii.edu/Instruments/Spectroscopy/Espadons/Espadons_FAQ.html)，本项目不声明绝对连续谱偏振能力。标定数量和流程分别参考 [CFHT 标定建议](https://www.cfht.hawaii.edu/Instruments/Spectroscopy/Espadons/Espadons_calibrations.html)与 [Libre-ESpRIT 流程](https://www.cfht.hawaii.edu/Instruments/Spectroscopy/Espadons/Espadons_esprit.html)。
