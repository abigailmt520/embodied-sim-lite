# -*- coding: utf-8 -*-
"""
physics_injection.py  ——  Phase1a · 物理自欺注入器（藏积分器内部，仅供能量审计自证抓假）
============================================================================================
对应契约层 fault_injection.py 的「物理层」版本。这里注入的不是对已记录 session 的事后篡改，
而是对 embodied_env 动力学积分核 (_integrate_dynamics) 的**真实破坏**——必须在仿真运行时生效，
因为物理故障会改变轨迹本身（无法事后注入）。

每个注入器返回一个 `physics_fault` 配置字典，赋给 env.physics_fault 即生效；env=None 即清洁。
关键：注入器只改「实际积分」用的参数，而能量账本 (W_act/D_damp/E_kin) 仍按 env 的**声称常数**
（MASS/C_LIN/...）结算 → 真实动能变化 ΔE 与声称能量预算 (W_act−D_damp) 出现残差，被能量审计抓。

五类物理自欺（破坏不同守恒律）：
    P-1 负阻尼/增益      —— 实际阻尼取负 → 能量凭空增（破坏热力学第二定律）。
    P-2 力到加速度双计    —— 实际力 ×2 而账本按单倍 → 动能增量超执行器做功（破坏牛顿一致性）。
    P-3 丢耗散却谎称守恒  —— 实际积分丢掉阻尼项，账本却仍上报 D_damp（破坏能量账本自洽，物理版波将金村）。
    P-4 速度越执行器上限  —— 跳过惯性滞后且过冲 → 速度越物理上限 + 动能跃变（破坏执行器功率界）。
    P-5 谎报质量/惯量    —— 实际积分用半质量、账本用声称质量 → 动能与预算不自洽（破坏能量自洽）。
"""


def clean(env=None):
    """清洁档：清除任何物理故障（env.physics_fault=None）。"""
    if env is not None:
        env.physics_fault = None
    return None


def inject_p1_neg_damp(env):
    """P-1：实际阻尼系数取负（−C_LIN/−C_ANG）→ 阻尼变「增益」，每步无功增能。"""
    fault = {"mode": "P-1_neg_damp",
             "c_lin_eff": -env.C_LIN, "c_ang_eff": -env.C_ANG}
    env.physics_fault = fault
    return fault


def inject_p2_force_double(env):
    """P-2：实际积分用 2× 力，账本按单倍力结算 → 动能增量超执行器做功。"""
    fault = {"mode": "P-2_force_double", "force_mult": 2.0}
    env.physics_fault = fault
    return fault


def inject_p3_drop_dissipation(env):
    """P-3：实际积分丢掉阻尼耗散项（c_eff=0），账本却仍按声称 C_LIN 上报 D_damp（谎称守恒）。"""
    fault = {"mode": "P-3_drop_dissipation",
             "c_lin_eff": 0.0, "c_ang_eff": 0.0}
    env.physics_fault = fault
    return fault


def inject_p4_skip_lag(env):
    """P-4：跳过惯性滞后且 1.5× 过冲 → 实际速度越执行器上限 + 动能凭空跃变。"""
    fault = {"mode": "P-4_skip_lag", "skip_lag": True, "overshoot": 1.5}
    env.physics_fault = fault
    return fault


def inject_p5_mass_misreport(env):
    """P-5：实际积分用半质量（更易加速），账本/动能用声称质量 → 动能与预算不自洽。"""
    fault = {"mode": "P-5_mass_misreport", "m_eff": 0.5 * env.MASS}
    env.physics_fault = fault
    return fault


INJECTORS = {
    "P-1_neg_damp": inject_p1_neg_damp,
    "P-2_force_double": inject_p2_force_double,
    "P-3_drop_dissipation": inject_p3_drop_dissipation,
    "P-4_skip_lag": inject_p4_skip_lag,
    "P-5_mass_misreport": inject_p5_mass_misreport,
}

DESCRIPTIONS = {
    "P-1_neg_damp": "实际阻尼取负→能量凭空增（破坏热力学第二定律）",
    "P-2_force_double": "实际力×2、账本按单倍→动能增量超做功（破坏牛顿一致性）",
    "P-3_drop_dissipation": "积分丢阻尼项、账本仍报耗散→谎称守恒（能量账本自洽破坏）",
    "P-4_skip_lag": "跳惯性+过冲→速度越执行器上限+动能跃变（执行器功率界破坏）",
    "P-5_mass_misreport": "实际半质量、账本声称质量→动能与预算不自洽（能量自洽破坏）",
}

# 每个注入器「期望被判红」的能量审计检查项（特征检查；据实测守恒律破坏签名标定）
# EC1 能量预算残差是「万能网」——5 类全被它抓（无漏网）；EC2/EC3 提供特异定位。
EXPECTED_CHECK = {
    "P-1_neg_damp": "EC2_NO_FREE_ENERGY",     # 特征：能量凭空增（ΔE>W_act），第二定律
    "P-2_force_double": "EC1_ENERGY_BUDGET",   # 特征：力/做功不一致 → 预算残差（牛顿一致性）
    "P-3_drop_dissipation": "EC1_ENERGY_BUDGET",  # 特征：幽灵耗散 → 预算残差（账本自洽）
    "P-4_skip_lag": "EC3_ACTUATOR_BOUND",     # 特征：速度越执行器上限
    "P-5_mass_misreport": "EC1_ENERGY_BUDGET",  # 特征：动能与预算不自洽（需暂态方可观测）
}
