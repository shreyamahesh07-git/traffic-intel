"""
Deep Q-Network Agent for Multi-Junction Connected Smart City Traffic Control.
Implements Dueling Double-DQN with Experience Replay, Target Network,
and Huber Loss for robust convergence on continuous urban traffic flows.
"""

import os
import sys
import random
from collections import deque
from typing import Tuple, List, Dict, Any, Optional

import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from backend.config import DQN_MODEL_PATH

class DuelingDQNNetwork(nn.Module):
    """
    Dueling DQN Architecture.
    Separates state-value V(s) and advantage A(s, a) streams:
    Q(s, a) = V(s) + (A(s, a) - mean(A(s, a)))
    Enables more stable and accurate value estimation in traffic scenarios.
    """
    def __init__(self, state_dim: int = 32, action_dim: int = 4):
        super(DuelingDQNNetwork, self).__init__()
        
        # Shared feature representation
        self.feature_net = nn.Sequential(
            nn.Linear(state_dim, 128),
            nn.LayerNorm(128),
            nn.ReLU(),
            nn.Linear(128, 128),
            nn.ReLU()
        )
        
        # State Value Stream V(s)
        self.value_stream = nn.Sequential(
            nn.Linear(128, 64),
            nn.ReLU(),
            nn.Linear(64, 1)
        )
        
        # Advantage Stream A(s, a)
        self.advantage_stream = nn.Sequential(
            nn.Linear(128, 64),
            nn.ReLU(),
            nn.Linear(64, action_dim)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        features = self.feature_net(x)
        values = self.value_stream(features)
        advantages = self.advantage_stream(features)
        # Combine streams: Q = V + (A - mean(A))
        q_values = values + (advantages - advantages.mean(dim=1, keepdim=True))
        return q_values

class ReplayBuffer:
    """Cyclic Experience Replay Buffer for off-policy training."""
    def __init__(self, capacity: int = 15000):
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

class CityDQNAgent:
    """
    Multi-Junction Adaptive City DQN Agent.
    Evaluates traffic states across 5 signalized junctions and selects
    optimal phase actuation decisions to minimize delay and prevent queue accumulation.
    """
    def __init__(
        self,
        state_dim: int = 32,
        action_dim: int = 4,
        lr: float = 7e-4,
        gamma: float = 0.95,
        epsilon_start: float = 1.0,
        epsilon_min: float = 0.05,
        epsilon_decay: float = 0.985,
        device: str = "cpu"
    ):
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.gamma = gamma
        self.epsilon = epsilon_start
        self.epsilon_min = epsilon_min
        self.epsilon_decay = epsilon_decay
        self.device = torch.device(device)

        # Policy & Target Networks
        self.policy_net = DuelingDQNNetwork(state_dim, action_dim).to(self.device)
        self.target_net = DuelingDQNNetwork(state_dim, action_dim).to(self.device)
        self.target_net.load_state_dict(self.policy_net.state_dict())
        self.target_net.eval()

        self.optimizer = optim.Adam(self.policy_net.parameters(), lr=lr)
        self.criterion = nn.SmoothL1Loss()  # Huber Loss for gradient stability
        self.replay_buffer = ReplayBuffer(capacity=15000)
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
        """Decays exploration epsilon."""
        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)

    def train_step(self, batch_size: int = 32) -> Optional[float]:
        """Performs Double-DQN gradient update."""
        if len(self.replay_buffer) < batch_size:
            return None

        states, actions, rewards, next_states, dones = self.replay_buffer.sample(batch_size)
        states = states.to(self.device)
        actions = actions.to(self.device)
        rewards = rewards.to(self.device)
        next_states = next_states.to(self.device)
        dones = dones.to(self.device)

        # Current Q: Q_policy(s, a)
        curr_q = self.policy_net(states).gather(1, actions.unsqueeze(1)).squeeze(1)

        # Double DQN Target:
        # 1. Best action from policy net: a* = argmax_a Q_policy(s', a)
        # 2. Target Q from target net: Q_target(s', a*)
        with torch.no_grad():
            best_next_actions = self.policy_net(next_states).argmax(dim=1, keepdim=True)
            max_next_q = self.target_net(next_states).gather(1, best_next_actions).squeeze(1)
            target_q = rewards + (1.0 - dones) * self.gamma * max_next_q

        loss = self.criterion(curr_q, target_q)

        self.optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(self.policy_net.parameters(), max_norm=1.0)
        self.optimizer.step()

        self.step_count += 1
        # Synchronize target network every 50 gradient steps
        if self.step_count % 50 == 0:
            self.target_net.load_state_dict(self.policy_net.state_dict())

        return float(loss.item())

    def save(self, path: str = DQN_MODEL_PATH):
        """Save model checkpoint to disk."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        torch.save({
            "model_state_dict": self.policy_net.state_dict(),
            "target_state_dict": self.target_net.state_dict(),
            "epsilon": self.epsilon,
            "step_count": self.step_count,
            "state_dim": self.state_dim,
            "action_dim": self.action_dim
        }, path)
        print(f"CityDQNAgent: Saved model weights to {path}")

    def load(self, path: str = DQN_MODEL_PATH):
        """Load model checkpoint from disk."""
        if not os.path.exists(path):
            raise FileNotFoundError(f"DQN weights not found at {path}")
        checkpoint = torch.load(path, map_location=self.device)
        self.policy_net.load_state_dict(checkpoint["model_state_dict"])
        self.target_net.load_state_dict(checkpoint["target_state_dict"])
        self.epsilon = checkpoint.get("epsilon", self.epsilon_min)
        self.step_count = checkpoint.get("step_count", 0)
        self.policy_net.eval()
        self.target_net.eval()
        print(f"CityDQNAgent: Successfully loaded weights from {path}")

