# G1 · PyBullet 真引擎泛化（独立环境）

测审计套件能否抓**独立第三方引擎(PyBullet)自己的原生数值病理**（非循环），并把契约/joint 移植到 3D。
审计逻辑复用 2D 平台 `../audit/`（integrity_audit / joint_audit）；2D 平台本身不改。

## 环境（独立 conda env，不动 base）
PyBullet 在 Python 3.13 / 新 macOS 无 wheel、源码编译失败 → 用 conda-forge 预编译二进制，建独立 env：
```bash
conda create -n g1-pybullet -c conda-forge python=3.13 pybullet numpy scipy matplotlib -y
```

## 运行
注：`cross_fidelity.py` 需在 env 内补 `gymnasium`（`conda run -n g1-pybullet pip install gymnasium`，**不引 torch/sb3**）。
```bash
conda run -n g1-pybullet python g1_pybullet/g1a_baseline.py     # 健康基线 + 噪声本底（检查点1）
conda run -n g1-pybullet python g1_pybullet/g1b_tunneling.py    # 原生高速穿模 → 物理审计（检查点2·皇冠）
conda run -n g1-pybullet python g1_pybullet/g1c_pathologies.py  # 能量注入 + 契约层 + joint（3D）
conda run -n g1-pybullet python g1_pybullet/cross_fidelity.py   # Cross-Fidelity D2 能量对照（孪生过自检 vs 跨保真预言）
```

## 文件
- `pb_helpers.py` —— 场景/孪生上报(OdomReporter)/不变量/审计复用层（含扫掠 EC5'、能量守恒上界）。
- `g1a_baseline.py` / `g1b_tunneling.py` / `g1c_pathologies.py` —— 三阶段。
- `cross_fidelity.py` —— **Cross-Fidelity D2 能量对照**：PyBullet(现实) vs 2D 简化孪生(report) 同进程双跑，
  证"内部一致≠与现实一致"（孪生过 EC1–EC5，接触处账面能量被跨保真预言抓背离）。详见 `../docs/CrossFidelity-Energy.md`。

## 关键结果（详见 ../docs/G1-PyBullet-Generalization.md）
- 引擎能量噪声本底 ≈ 8.3e-4 J/step（审计阈值须 > 此）。
- 高速穿模（200 m/s）：引擎自报穿透=0（完全漏检），**唯 EC5' 扫掠抓到**（非循环·皇冠）。
- 能量注入（弹性反弹 e=1）：能量守恒上界审计抓到。
- 契约 C1-C3 在 3D 移植：健康零误报 + 注入器（odom=truth / seq 冻结）各抓。
- warm-start 幽灵力：未干净测出（隔离难，诚实负/不定）。
