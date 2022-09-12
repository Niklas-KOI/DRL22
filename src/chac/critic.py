import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from src.chac.utils import Base, hidden_init


class Critic(Base):
    """The actor network with MLPs consisting of 3 hidden layers of size 256"""
    def __init__(self, env, level, n_levels, time_scale, gamma=0.98):

        super(Critic, self).__init__()

        hidden_size=64
        lr=0.001
        self.gamma = gamma
        self.q_limit = -time_scale

        # Dimensions of goal placeholder will differ depending on layer level
        goal_dim = env.end_goal_dim if level == n_levels - 1 else env.subgoal_dim

        # Dimensions of action placeholder will differ depending on layer level
        action_dim = env.action_dim if level == 0 else env.subgoal_dim

        # Set parameters to give critic optimistic initialization near q_init
        self.q_init = -0.067
        self.q_offset = -torch.tensor([self.q_limit / self.q_init - 1]).log()
        
        # Network layers
        self.fc1 = nn.Linear(env.state_dim + action_dim + goal_dim, hidden_size)
        self.fc2 = nn.Linear(hidden_size, hidden_size)
        self.fc3 = nn.Linear(hidden_size, hidden_size)
        self.fc4 = nn.Linear(hidden_size, 1)

        self.critic_optimizer = optim.Adam(self.parameters(), lr)
        self.mse_loss = nn.MSELoss()

        self.reset_parameters()

    def forward(self, state, goal, action):
        x = torch.cat([state, action, goal], dim=1)
        x = F.relu(self.fc1(x))
        x = F.relu(self.fc2(x))
        x = F.relu(self.fc3(x))
        # TODO: explain this
        return torch.sigmoid(self.fc4(x) + self.q_offset) * self.q_limit

    def reset_parameters(self):
        self.fc1.weight.data.uniform_(*hidden_init(self.fc1))
        self.fc2.weight.data.uniform_(*hidden_init(self.fc2))
        self.fc3.weight.data.uniform_(*hidden_init(self.fc3))
        self.fc4.weight.data.uniform_(-3e-3, 3e-3)

        self.fc1.bias.data.uniform_(*hidden_init(self.fc1))
        self.fc2.bias.data.uniform_(*hidden_init(self.fc2))
        self.fc3.bias.data.uniform_(*hidden_init(self.fc3))
        self.fc4.bias.data.uniform_(-3e-3, 3e-3)

    def update(self, states, actions, rewards, new_states, goals, new_actions, done):
        next_q = self(new_states, goals, new_actions)
        target_q = rewards + (self.gamma * next_q * (1. - done)).detach()
        current_q = self(states, goals, actions)

        critic_loss = self.mse_loss(current_q, target_q)
        self.critic_optimizer.zero_grad()
        critic_loss.backward()
        flat_grads = torch.cat([param.flatten() for _, param in self.named_parameters()])
        self.critic_optimizer.step()

        return {
            'q_loss': critic_loss.item(),
            'target_q': target_q.mean().item(),
            'next_q': next_q.mean().item(),
            'current_q': current_q.mean().item(),
            'q_grads': flat_grads.mean().item(),
            'q_grads_std': flat_grads.std().item(),
        }
