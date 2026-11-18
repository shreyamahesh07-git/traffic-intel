import os
import sys
import json
import time
from typing import List, Dict, Any

# Load backend configuration
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from backend.config import DQN_MODEL_PATH, DATA_DIR
from backend.rlagent.dqn_agent import DQNAgent
from backend.rlagent.sumo_env import SumoRLEnvironment

def train_dqn(num_episodes: int = 5, steps_per_episode: int = 120, batch_size: int = 32):
    """
    Trains Deep Q-Network on SUMO intersection environment.
    Optimizes signal timing policy and saves trained weights to disk.
    """
    print(f"=== Starting DQN Training ({num_episodes} episodes, {steps_per_episode} steps/ep) ===")
    os.makedirs(os.path.dirname(DQN_MODEL_PATH), exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    agent = DQNAgent(state_dim=16, action_dim=2, lr=1e-3, gamma=0.95, epsilon_start=1.0, epsilon_decay=0.98)
    env = SumoRLEnvironment(use_gui=False, episode_steps=steps_per_episode)

    training_history = []
    start_time = time.time()

    for episode in range(1, num_episodes + 1):
        ep_start = time.time()
        state = env.reset()
        episode_reward = 0.0
        losses = []
        action_counts = {0: 0, 1: 0}

        for step in range(steps_per_episode):
            # Select action via epsilon-greedy policy
            action = agent.select_action(state, eval_mode=False)
            action_counts[action] += 1

            next_state, reward, done, info = env.step(action)
            episode_reward += reward

            # Store transition in replay buffer
            agent.replay_buffer.push(state, action, reward, next_state, done)
            state = next_state

            # Perform training step
            loss = agent.train_step(batch_size=batch_size)
            if loss is not None:
                losses.append(loss)

            if done:
                break

        # Decay exploration rate
        agent.update_epsilon()

        avg_loss = round(sum(losses) / len(losses), 4) if losses else 0.0
        ep_duration = round(time.time() - ep_start, 1)

        ep_stat = {
            "episode": episode,
            "total_reward": round(episode_reward, 2),
            "avg_loss": avg_loss,
            "epsilon": round(agent.epsilon, 3),
            "actions": action_counts,
            "duration_sec": ep_duration
        }
        training_history.append(ep_stat)

        print(f"Episode {episode:02d}/{num_episodes:02d} | Reward: {ep_stat['total_reward']:8.2f} | Avg Loss: {avg_loss:.4f} | Eps: {agent.epsilon:.3f} | Actions (Keep={action_counts[0]}, Switch={action_counts[1]}) | Time: {ep_duration}s")

    env.close()
    
    # Save trained model weights
    agent.save(DQN_MODEL_PATH)
    
    # Save training metrics log
    metrics_path = os.path.join(DATA_DIR, "training_metrics.json")
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump({
            "total_training_time_sec": round(time.time() - start_time, 1),
            "episodes": training_history
        }, f, indent=2)
    print(f"Saved training history to {metrics_path}")
    print("=== DQN Training Completed Successfully ===")

if __name__ == "__main__":
    train_dqn(num_episodes=5, steps_per_episode=120, batch_size=32)

