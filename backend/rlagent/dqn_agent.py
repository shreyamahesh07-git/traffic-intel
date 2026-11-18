import os
import sys
import random
from collections import deque
from typing import Tuple, List, Dict, Any, Optional

import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np

# Load backend configuration
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from backend.config import DQN_MODEL_PATH

class DQNNetwork(nn.Module):
    """
    Multi-layer Perceptron for Deep Q-Learning.
    Maps 16-dimensional continuous intersection state vector to Q-values for each discrete action.
    """
    def __init__(self, state_dim: int = 16, action_dim: int = 2):
        super(DQNNetwork, self).__init__()
        self.net = nn.Sequential(
            nn.Linear(state_dim, 128),
            nn.ReLU(),
            nn.Linear(128, 128),
            nn.ReLU(),
            nn.Linear(128, 64),
            nn.ReLU(),
            nn.Linear(64, action_dim)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)

class ReplayBuffer:
    """Experience Replay Buffer for off-policy DQN training."""
    def __init__(self, capacity: int = 10000):
        self.buffer = deque(maxlen=capacity)

    def push(self, state, action, reward, next_state, done):
        self.buffer.append((state, action, reward, next_state, done))

    def sample(self, batch_size: int):
        batch = random.sample(self.buffer, batch_size)
        states, actions, rewards, next_states, dones = zip(*batch)
        return (
            torch.FloatTensor(np.array(states)),
            torch.LongTensor(actions),
            torch.FloatTensor(rewards),
            torch.FloatTensor(np.array(next_states)),
            torch.FloatTensor(dones)
        )

    def __len__(self):
        return len(self.buffer)

class DQNAgent:
    """
    Deep Q-Network Agent for Adaptive Traffic Signal Optimization.
    Selects actions to minimize queue lengths and vehicle waiting times.
    """
    def __init__(
        self,
        state_dim: int = 16,
        action_dim: int = 2,
        lr: float = 1e-3,
        gamma: float = 0.95,
        epsilon_start: float = 1.0,
        epsilon_min: float = 0.05,
        epsilon_decay: float = 0.995,
        device: str = "cpu"
    ):
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.gamma = gamma
        self.epsilon = epsilon_start
        self.epsilon_min = epsilon_min
        self.epsilon_decay = epsilon_decay
        self.device = torch.device(device)

        # Policy and Target Networks
        self.policy_net = DQNNetwork(state_dim, action_dim).to(self.device)
        self.target_net = DQNNetwork(state_dim, action_dim).to(self.device)
        self.target_net.load_state_dict(self.policy_net.state_dict())
        self.target_net.eval()

        self.optimizer = optim.Adam(self.policy_net.parameters(), lr=lr)
        self.criterion = nn.SmoothL1Loss()  # Huber loss for stability
        self.replay_buffer = ReplayBuffer(capacity=10000)
        self.step_count = 0

    def select_action(self, state: List[float], eval_mode: bool = False) -> int:
        """Epsilon-greedy action selection."""
        if not eval_mode and random.random() < self.epsilon:
            return random.randint(0, self.action_dim - 1)
        
        state_tensor = torch.FloatTensor(state).unsqueeze(0).to(self.device)
        with torch.no_grad():
            q_values = self.policy_net(state_tensor)
            return int(q_values.argmax(dim=1).item())

    def update_epsilon(self):
        """Decay exploration rate."""
        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)

    def train_step(self, batch_size: int = 32) -> Optional[float]:
        """Perform one gradient descent optimization step on a mini-batch from replay buffer."""
        if len(self.replay_buffer) < batch_size:
            return None

        states, actions, rewards, next_states, dones = self.replay_buffer.sample(batch_size)
        states = states.to(self.device)
        actions = actions.to(self.device)
        rewards = rewards.to(self.device)
        next_states = next_states.to(self.device)
        dones = dones.to(self.device)

        # Current Q-values: Q(s, a)
        curr_q = self.policy_net(states).gather(1, actions.unsqueeze(1)).squeeze(1)

        # Target Q-values: r + gamma * max_a' Q_target(s', a')
        with torch.no_grad():
            max_next_q = self.target_net(next_states).max(dim=1)[0]
            target_q = rewards + (1.0 - dones) * self.gamma * max_next_q

        loss = self.criterion(curr_q, target_q)

        self.optimizer.zero_grad()
        loss.backward()
        # Gradient clipping for training stability
        torch.nn.utils.clip_grad_norm_(self.policy_net.parameters(), max_norm=1.0)
        self.optimizer.step()

        self.step_count += 1
        # Update target network every 100 training steps
        if self.step_count % 100 == 0:
            self.update_target_network()

        return float(loss.item())

    def update_target_network(self):
        """Synchronize target network with policy network."""
        self.target_net.load_state_dict(self.policy_net.state_dict())

    def save(self, path: str = DQN_MODEL_PATH):
        """Save trained network weights to disk."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        torch.save({
            "model_state_dict": self.policy_net.state_dict(),
            "target_state_dict": self.target_net.state_dict(),
            "epsilon": self.epsilon,
            "step_count": self.step_count
        }, path)
        print(f"DQNAgent: Saved model weights to {path}")

    def load(self, path: str = DQN_MODEL_PATH):
        """Load trained network weights from disk."""
        if not os.path.exists(path):
            raise FileNotFoundError(f"DQN weights file not found at {path}")
        checkpoint = torch.load(path, map_location=self.device)
        self.policy_net.load_state_dict(checkpoint["model_state_dict"])
        self.target_net.load_state_dict(checkpoint["target_state_dict"])
        self.epsilon = checkpoint.get("epsilon", self.epsilon_min)
        self.step_count = checkpoint.get("step_count", 0)
        self.policy_net.eval()
        self.target_net.eval()
        print(f"DQNAgent: Loaded model weights from {path}")

if __name__ == "__main__":
    print("Testing DQNAgent initialization and forward pass...")
    agent = DQNAgent()
    dummy_state = [0.1] * 16
    action = agent.select_action(dummy_state, eval_mode=True)
    print(f"Selected action for dummy state: {action} (Action 0=Keep, Action 1=Switch)")
    
    # Test experience replay and training step
    for _ in range(50):
        s = [random.random() for _ in range(16)]
        a = random.randint(0, 1)
        r = -random.random() * 5.0
        s_ = [random.random() for _ in range(16)]
        agent.replay_buffer.push(s, a, r, s_, False)
        
    loss = agent.train_step(batch_size=32)
    print(f"Training step loss: {loss:.4f}")
    agent.save(DQN_MODEL_PATH)
    agent.load(DQN_MODEL_PATH)
    print("DQNAgent verified successfully!")

