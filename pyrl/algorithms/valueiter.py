# code for value iteration algorithms, such as Q-learning, SARSA, etc.
# this refractors the old dqn.py module by decoupling agent and algorithms.
import theano
import theano.tensor as T
import random
import numpy as np
import numpy.random as npr

import pyrl.optimizers as optimizers
import pyrl.layers as layers
from pyrl.tasks.task import Task
from pyrl.agents.agent import DQN
from pyrl.agents.agent import TabularVfunc

class ValueIterationSolver(object):
    '''
    Vanilla value iteration for tabular environment
    '''
    def __init__(self, task, vfunc = None, tol=1e-3):
        self.task = task
        self.num_states = task.get_num_states()
        self.gamma = task.gamma
        self.tol = tol
        if vfunc:
            self.vfunc = vfunc
        else:
            self.vfunc = TabularVfunc(self.num_states)

    def get_action(self, state):
        '''Returns the greedy action with respect to the current policy'''
        poss_actions = self.task.get_allowed_actions(state)

        # compute a^* = \argmax_{a} Q(s, a)
        best_action = None
        best_val = -float('inf')
        for action in poss_actions:
            ns_dist = self.task.next_state_distribution(state, action)

            val = 0.
            for ns, prob in ns_dist:
                val += prob * self.gamma * self.vfunc(ns)

            if val > best_val:
                best_action = action
                best_val = val
            elif val == best_val and random.random() < 0.5:
                best_action = action
                best_val = val

        return best_action

    def learn(self):
        ''' Performs value iteration on the MDP until convergence '''
        while True:
            # repeatedly perform the Bellman backup on each state
            # V_{i+1}(s) = \max_{a} \sum_{s' \in NS} T(s, a, s')[R(s, a, s') + \gamma V(s')]
            max_diff = 0.

            # TODO: Add priority sweeping for state in xrange(self.num_states):
            for state in self.task.env.get_valid_states():
                poss_actions = self.task.get_allowed_actions(state)

                best_val = 0.
                for idx, action in enumerate(poss_actions):
                    val = 0.
                    ns_dist = self.task.next_state_distribution(state, action)
                    for ns, prob in ns_dist:
                        val += prob * (self.task.get_reward(state, action, ns) +
                                       self.gamma * self.vfunc(ns))

                    if(idx == 0 or val > best_val):
                        best_val = val

                diff = abs(self.vfunc(state) - best_val)
                self.vfunc.update(state, best_val)

                if diff > max_diff:
                    max_diff = diff

            if max_diff < self.tol:
                break


class DeepQlearn(object):
    '''
    DeepMind's deep Q learning algorithms.
    '''
    def __init__(self, task, dqn_mt, l2_reg=0.0, lr=1e-3,
               memory_size=250, minibatch_size=64, epsilon=0.05):
        '''
        (TODO): task should be task info.
        we don't use all of task properties/methods here.
        only gamma and state dimension.
        and we allow task switching.
        '''
        self.dqn = dqn_mt
        self.l2_reg = l2_reg
        self.lr = lr
        self.epsilon = epsilon
        self.memory_size = memory_size
        self.minibatch_size = minibatch_size
        self.state_dim = task.get_state_dimension()
        self.gamma = task.gamma
        self.task = task

        # for now, keep experience as a list of tuples
        self.experience = []
        self.experience_task = [] # which task an experience example comes from.
        self.exp_idx = 0

        # used for streaming updates
        self.last_state_vector = None
        self.last_action = None

        # compile back-propagtion network
        self._compile_bp()

    def _compile_bp(self):
        states = self.dqn.states
        action_values = self.dqn.action_values
        params = self.dqn.params
        targets = T.vector('target')
        last_actions = T.lvector('action')

        # loss function.
        mse = layers.MSE(action_values[T.arange(action_values.shape[0]),
                            last_actions], targets)
        # l2 penalty.
        l2_penalty = 0.
        for param in params:
            l2_penalty += (param ** 2).sum()

        cost = mse + self.l2_reg * l2_penalty

        # back propagation.
        updates = optimizers.Adam(cost, params, alpha=self.lr)

        td_errors = T.sqrt(mse)
        self.bprop = theano.function(inputs=[states, last_actions, targets],
                                     outputs=td_errors, updates=updates)

    def _add_to_experience(self, s, a, ns, r):
        # TODO: improve experience replay mechanism by making it harder to
        # evict experiences with high td_error, for example
        # s, ns are state_vectors.
        if len(self.experience) < self.memory_size:
            self.experience.append((s, a, ns, r))
            self.experience_task.append(self.task)
        else:
            self.experience[self.exp_idx] = (s, a, ns, r)
            self.experience_task[self.exp_idx] = self.task
            self.exp_idx += 1
            if self.exp_idx >= self.memory_size:
                self.exp_idx = 0

    def _update_net(self):
        '''
            sample from the memory dataset and perform gradient descent on
            (target - Q(s, a))^2
        '''
        # don't update the network until sufficient experience has been
        # accumulated
        if len(self.experience) < self.memory_size:
            return

        states = np.zeros((self.minibatch_size, self.state_dim,))
        next_states = np.zeros((self.minibatch_size, self.state_dim))
        actions = np.zeros(self.minibatch_size, dtype=int)
        rewards = np.zeros(self.minibatch_size)

        # sample and process minibatch
        samples = random.sample(self.experience, self.minibatch_size)
        terminals = []
        for idx, sample in enumerate(samples):
            state_vector, action, next_state_vector, reward = sample

            states[idx, :] = state_vector.reshape(-1)
            actions[idx] = action
            rewards[idx] = reward

            if next_state_vector is not None:
                next_states[idx, :] = next_state_vector.reshape(-1)
            else:
                terminals.append(idx)

        # compute target reward + \gamma max_{a'} Q(ns, a')
        next_qvals = np.max(self.dqn.fprop(next_states), axis=1)

        # Ensure target = reward when NEXT_STATE is terminal
        next_qvals[terminals] = 0.

        targets = rewards + self.task.gamma * next_qvals

        self.bprop(states, actions, targets.flatten())

    def _learn(self, next_state_vector, reward):
        self._add_to_experience(self.last_state_vector, self.last_action,
                                next_state_vector, reward)
        self._update_net()

    def _end_episode(self, reward):
        if self.last_state_vector is not None:
            self._add_to_experience(self.last_state_vector, self.last_action, None,
                                    reward)
        self.last_state_vector = None
        self.last_action = None


    def run(self, budget = 100, tol=1e-6):
        task = self.task

        total_steps = 0.
        while True:
            task.reset()
            while task.is_terminal():
                task.reset()

            curr_state = task.get_current_state()

            num_steps = 0.
            while True:
                # TODO: Hack!
                if num_steps >= np.log(tol) / np.log(task.gamma):
                    # print 'Lying and tell the agent the episode is over!'
                    self._end_episode(0)
                    break

                curr_state_vector = task.wrap_stateid(curr_state)
                action = self.dqn.get_action(curr_state_vector, method='eps-greedy', epsilon=self.epsilon)
                self.last_state_vector = curr_state_vector
                self.last_action = action

                next_state, reward = task.perform_action(action)
                next_state_vector = task.wrap_stateid(next_state)

                if task.is_terminal():
                    self._end_episode(reward)
                    break
                else:
                    self._learn(next_state_vector, reward)
                    curr_state = next_state

                num_steps += 1
                total_steps += 1

                if total_steps >= budget:
                    return


def compute_tabular_value(task, tol=1e-4):
    solver = ValueIterationSolver(task, tol=tol)
    solver.learn()
    return solver.vfunc.V

def eval_tabular_value(task, func):
    V = np.zeros(task.get_num_states())
    for state in range(task.get_num_states()):
        V[state] = func(state)
    return V

def compute_tabular_values(tasks, num_cores = 8):
    ''' take a list of tabular tasks, and return states x tasks value matrix.
    '''
    vals = map(compute_tabular_value, tasks)
    return np.transpose(np.array(vals))
