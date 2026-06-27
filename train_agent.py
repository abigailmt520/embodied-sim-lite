# -*- coding: utf-8 -*-
"""
train_agent.py
==============
「算力置换架构」之训练态：超实时（Hyper-real-time）PPO 训练脚本。

核心原则——彻底剥离调度外壳：
    本脚本只与 embodied_env.py 的纯计算内核交互，**完全不 import** fastapi / websockets，
    更没有任何 asyncio.sleep / 60Hz 心跳。环境以 env.step() 的同步函数调用形式被 PPO
    的 rollout 收集器以 CPU 极限速度反复驱动——这正是把「实时渲染/通信算力」置换为
    「纯训练算力」的工程落点：单核满载狂奔，时钟节流为零。

监控：接入 TensorBoard，自动记录 rollout/ep_rew_mean（累计奖励收敛曲线）等指标。
产物：训练权重保存为 ppo_embodied_agent.pth（policy 的 state_dict）。
"""

import os

import torch
from stable_baselines3 import PPO
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.vec_env import DummyVecEnv
from stable_baselines3.common.callbacks import CheckpointCallback, BaseCallback

from embodied_env import EmbodiedNavEnv

# ====================== 训练超参 ======================
# 可由环境变量覆盖（dev 分支：默认产出 *_dyn 权重，绝不覆盖论文 .pth / dyn.pth）
TOTAL_TIMESTEPS = int(os.environ.get("EMBODIED_TIMESTEPS", 1_000_000))  # 总训练步数
CONTROL_MODE = os.environ.get("EMBODIED_CONTROL_MODE", "A")             # 'A'=目标速度 / 'B'=力控
MAP_TYPE = os.environ.get("EMBODIED_MAP_TYPE", "random_circle")         # 'random_circle' / 'maze'
MODEL_PATH = os.environ.get("EMBODIED_MODEL_PATH", "ppo_embodied_agent_dyn.pth")  # 权重输出
SB3_NATIVE_PATH = os.environ.get("EMBODIED_SB3_PATH", "ppo_embodied_agent_dyn")   # SB3 原生 zip
CKPT_PREFIX = os.environ.get("EMBODIED_CKPT_PREFIX", "ppo_dyn_ckpt")    # 检查点前缀
TB_LOG_DIR = "./tb_embodied/"      # TensorBoard 日志目录
CHECKPOINT_DIR = "./checkpoints/"  # 周期性检查点目录

# 策略网络结构：刻意保持轻量（两层 64 的 MLP），契合「轻量化底座」原则。
# 注意：推理脚本 inference_server.py 必须使用**完全相同**的 policy_kwargs，
#       否则 load_state_dict 会因层形状不匹配而失败。
POLICY_KWARGS = dict(net_arch=dict(pi=[64, 64], vf=[64, 64]))


class RewardLogCallback(BaseCallback):
    """轻量回调：把每个回合的累计奖励额外打到 TensorBoard 的 custom/ 命名空间，
    便于在 ep_rew_mean 之外做更细粒度的收敛观察。"""

    def _on_step(self) -> bool:
        # SB3 在 info["episode"] 中携带 Monitor 记录的回合统计（r=累计奖励, l=步数）
        for info in self.locals.get("infos", []):
            ep = info.get("episode")
            if ep is not None:
                self.logger.record("custom/episode_reward", ep["r"])
                self.logger.record("custom/episode_length", ep["l"])
                if info.get("is_success"):
                    self.logger.record("custom/success", 1.0)
        return True


# —— 涌现 gaming 实验：训练期可注入可利用物理故障（藏积分器内）——
#    G-1（被动型）：EMBODIED_BOOST_FORCE>0，高速白拿推力，与「求快」对齐 → 任意高速策略被动触发。
#    G-2（唯一习得型）：EMBODIED_G2_FORCE>0，近零推力滑行白拿大额前向力，唯有学会「切推力滑行」才获利。
BOOST_FORCE = float(os.environ.get("EMBODIED_BOOST_FORCE", 0.0))
BOOST_THRESH = float(os.environ.get("EMBODIED_BOOST_THRESH", 1.05))
G2_FORCE = float(os.environ.get("EMBODIED_G2_FORCE", 0.0))
G2_THRESH = float(os.environ.get("EMBODIED_G2_THRESH", 0.35))      # 净力近零阈值
G2_THRESH_TAU = float(os.environ.get("EMBODIED_G2_THRESH_TAU", 0.3))  # 力矩近零阈值（两轮都idle）


def make_env():
    """构造单环境（Monitor 包裹以采集回合统计）。
    单核满载场景下用 DummyVecEnv 单实例即可；若放开多核，把这里改成
    SubprocVecEnv + 多个 make_env 即可线性提速。"""
    env = EmbodiedNavEnv(render_mode=None, control_mode=CONTROL_MODE, map_type=MAP_TYPE)
    if BOOST_FORCE > 0.0:
        env.physics_fault = {"mode": "G-1_speed_boost",
                             "boost_force": BOOST_FORCE, "boost_thresh": BOOST_THRESH}
    elif G2_FORCE > 0.0:
        env.physics_fault = {"mode": "G-2_lazy_coast", "g2_force": G2_FORCE,
                             "g2_thresh": G2_THRESH, "g2_thresh_tau": G2_THRESH_TAU}
    env = Monitor(env)
    return env


def main():
    # 将 torch 线程数锁为 1：贴合「单核 CPU 满载狂奔」的算力置换设定，
    # 同时避免小网络在多线程下因调度开销反而变慢。
    torch.set_num_threads(1)

    vec_env = DummyVecEnv([make_env])

    model = PPO(
        policy="MlpPolicy",
        env=vec_env,
        learning_rate=3e-4,
        n_steps=2048,          # 单次 rollout 采样步数
        batch_size=256,
        n_epochs=10,
        gamma=0.99,            # 折扣因子：导航任务奖励较长程，取 0.99
        gae_lambda=0.95,
        clip_range=0.2,
        ent_coef=0.0,
        policy_kwargs=POLICY_KWARGS,
        tensorboard_log=TB_LOG_DIR,
        device="cpu",          # 轻量 MLP 在 CPU 上反而比 GPU 调度更快
        verbose=1,
    )

    callbacks = [
        RewardLogCallback(),
        CheckpointCallback(save_freq=50_000, save_path=CHECKPOINT_DIR,
                           name_prefix=CKPT_PREFIX),
    ]

    print(">>> 进入超实时训练循环（无网络/无异步时钟，单核满载）...")
    model.learn(total_timesteps=TOTAL_TIMESTEPS, callback=callbacks,
                progress_bar=True)

    # —— 产物保存 ——
    # (1) 按需求保存 policy 权重为 .pth（推理脚本以 load_state_dict 加载）
    torch.save(model.policy.state_dict(), MODEL_PATH)
    print(f">>> 权重已保存: {MODEL_PATH}")

    # (2) 同时保存 SB3 原生 zip 存档（包含完整超参/optimizer，最鲁棒，强烈建议保留）
    model.save(SB3_NATIVE_PATH)
    print(f">>> SB3 原生存档已保存: {SB3_NATIVE_PATH}.zip")
    print(">>> 训练完成。运行 `tensorboard --logdir ./tb_embodied/` 查看收敛曲线。")


if __name__ == "__main__":
    main()
