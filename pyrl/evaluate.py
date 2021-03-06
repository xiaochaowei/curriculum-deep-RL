from pyrl.common import *
from pyrl.tasks.task import Task, task_breakpoint
from pyrl.prob import choice
from pyrl.utils import get_val
from pyrl.algorithms.valueiter import compute_tabular_value


def estimate_temperature(policy, states, valid_actions, entropy = 0.3, tol=1e-1):
    '''
    given a set of states, binary search temperature so that the average entropy of policy
    is around given value.

    policy should support *get_action_distribution*.
    '''
    temperature_left = 0.
    temperature_right = 10.
    phase = 0

    iteration = 0.
    while True:
        if phase == 0:
            temperature = temperature_right
        else:
            temperature = (temperature_left + temperature_right) / 2.

        prob_entropy_list = []
        for (state, va) in zip(states, valid_actions):
            prob = policy.get_action_distribution(state, method='softmax', temperature=temperature, valid_actions=va)
            prob = prob.values()
            prob = [p for p in prob if p != 0.]
            prob_entropy = -np.sum(prob * np.log(prob))
            prob_entropy_list.append(prob_entropy)
        avg_prob_entropy = np.mean(prob_entropy_list)
        if np.abs(avg_prob_entropy - entropy) < tol:
            return temperature
        if temperature < 1e-100 or temperature > 1e100:
            #print '[warning] temperature = ', temperature
            return temperature
        elif avg_prob_entropy > entropy:
            if phase == 0:
                phase = 1
            else:
                temperature_right = temperature
        else:
            if phase == 0:
                temperature_right = 2 * temperature_right
            else:
                temperature_left = temperature

        if iteration >= 10000:
            print '[warning] temperature, too many iterations', temperature
            print prob
            return temperature
        iteration += 1


class DrunkLearner(object):
    '''
    a learner that never learns.
    '''
    def __init__(self):
        self.cum_reward = 0.


    def get_action(self, curr_state, valid_actions):
        action = choice(valid_actions, 1)[0]
        return action


    def send_feedback(self, reward, next_state, next_valid_actions, is_end):
        #print 'reward', reward, 'is_end', is_end
        self.cum_reward += reward


class DumbLearner(object):
    '''
    a learner that never learns.
    '''
    def __init__(self, dqn, method='eps-greedy', **kwargs):
        self.dqn = dqn
        self.method = method
        self.kwargs = kwargs
        self.cum_reward = 0.


    def get_action(self, curr_state, valid_actions):
        if self.method == 'eps-greedy':
            epsilon = get_val(self.kwargs, 'epsilon', 0.05)
            action = self.dqn.get_action(curr_state, valid_actions=valid_actions, method='eps-greedy', epsilon=epsilon)
        elif self.method == 'softmax-entropy':
            entropy = get_val(self.kwargs, 'entropy', 0.2)
            temperature = estimate_temperature(self.dqn, [curr_state], [valid_actions], entropy=entropy, tol=1e-2)
            action = self.dqn.get_action(curr_state, valid_actions=valid_actions, method='softmax', temperature=temperature)
        elif self.method == 'softmax-l2':
            av = self.dqn.av(curr_state)
            temperature = get_val(self.kwargs, 'temperature', 1.)
            temperature *= npla.norm(av)
            action = self.dqn.get_action(curr_state, valid_actions=valid_actions, method='softmax', temperature=temperature)

        return action


    def send_feedback(self, reward, next_state, next_valid_actions, is_end):
        self.cum_reward += reward
        pass # ignore, 'caz i am dumb learner.


def reward_simulator_samples(dqn, simulator, num_trials=10, max_steps=None, callback=None, method='eps-greedy', **kwargs):
    total_reward = []
    for ni in range(num_trials):
        learner = DumbLearner(dqn, method=method, **kwargs)
        cum_reward = simulator.run(learner, callback=callback, max_steps=max_steps)
        total_reward.append(cum_reward)
    return total_reward


def reward_simulator_mean_std(dqn, simulator, **kwargs):
    samples = reward_simulator_samples(dqn, simulator, **kwargs)
    return (np.mean(samples), np.std(samples))


def reward_search_samples(search_func, task, num_trials=10, gamma=0.95, tol=1e-2, entropy=0.1, callback=None):
    total_reward = []

    for ni in range(num_trials):
        num_steps = 0
        task.reset()
        reward = 0.
        factor = 1.
        while gamma == 1. or num_steps < np.log(tol) / np.log(gamma):
            curr_state = task.curr_state

            if callback:
                callback(task)

            sub_task = task_breakpoint(task)

            policy = search_func(sub_task)

            if task.is_end():
                break

            # estimate temperature.
            temperature = estimate_temperature(policy, [curr_state], [task.valid_actions], entropy=entropy, tol=1e-2)
            action = policy.get_action(curr_state, valid_actions=task.valid_actions, method='softmax', temperature=temperature)
            reward += factor * task.step(action)
            factor *= gamma
            num_steps += 1
        total_reward.append(reward)
        print 'trial', ni, 'reward', reward
    task.reset()
    return total_reward


def reward_search_mean_std(search_func, task, **kwargs):
    samples = reward_search_samples(search_func, task, **kwargs)
    return (np.mean(samples), np.std(samples))


def reward_stochastic_softmax_samples(policy, task, gamma=0.95, num_trials = 100, budget=None, tol=1e-6, entropy=0.2, callback=None):
    total_reward = []

    for ni in range(num_trials):
        num_steps = 0
        task.reset()
        reward = 0.
        factor = 1.
        while gamma == 1. or num_steps < np.log(tol) / np.log(gamma):
            curr_state = task.curr_state
            if callback:
                callback(task)

            if task.is_end():
                break

            if budget and num_steps >= budget:
                break

            # estimate temperature.
            temperature = estimate_temperature(policy, [curr_state], [task.valid_actions], entropy=entropy, tol=1e-2)
            action = policy.get_action(curr_state, valid_actions=task.valid_actions, method='softmax', temperature=temperature)
            reward += factor * task.step(action)
            factor *= gamma
            num_steps += 1
        total_reward.append(reward)
    task.reset()
    return total_reward


def reward_stochastic_samples(policy, task, gamma=0.95, num_trials = 100, budget=None, tol=1e-6, **args):
    total_reward = []

    for ni in range(num_trials):
        num_steps = 0
        task.reset()
        reward = 0.
        factor = 1.
        while gamma == 1. or num_steps < np.log(tol) / np.log(gamma):
            if task.is_end():
                break

            if budget and num_steps >= budget:
                break

            curr_state = task.curr_state
            # action = policy.get_action(curr_state, method='eps-greedy', epsilon=0., valid_actions=task.valid_actions)
            action = policy.get_action(curr_state, valid_actions=task.valid_actions, **args)
            reward += factor * task.step(action)
            factor *= gamma
            num_steps += 1
        total_reward.append(reward)
    task.reset()
    return total_reward


def qval_stochastic_samples(policy, task, gamma=0.95, num_trials = 100, budget=20, **args):
    total_reward = []

    for ni in range(num_trials):
        num_steps = 0
        task.reset()
        reward = 0.
        factor = 1.
        while True:
            if task.is_end():
                break

            if num_steps >= budget:
                action_values = policy.av(task.curr_state)
                value = max([action_values[act] for act in task.valid_actions])
                reward += factor * value
                break

            curr_state = task.curr_state
            # action = policy.get_action(curr_state, method='eps-greedy', epsilon=0., valid_actions=task.valid_actions)
            action = policy.get_action(curr_state, valid_actions=task.valid_actions, **args)
            reward += factor * task.step(action)
            factor *= gamma
            num_steps += 1
        total_reward.append(reward)
    task.reset()
    return total_reward

def qval2_stochastic_samples(dqn, dqn2, task, gamma=0.95, num_trials = 100, budget=20, **args):
    '''
    use the value from dqn2 as bootstrap.
    '''
    total_reward = []

    for ni in range(num_trials):
        num_steps = 0
        task.reset()
        reward = 0.
        factor = 1.
        while True:
            if task.is_end():
                break

            if num_steps >= budget:
                action_values = dqn2.fprop(np.array([task.curr_state]))[0]
                value = max([action_values[act] for act in task.valid_actions])
                reward += factor * value
                break

            curr_state = task.curr_state
            action = dqn.get_action(curr_state, valid_actions=task.valid_actions, **args)
            reward += factor * task.step(action)
            factor *= gamma
            num_steps += 1
        total_reward.append(reward)
    task.reset()
    return total_reward

def reward_stochastic(policy, task, gamma=0.95, num_trials=100, budget=None, tol=1e-6, **args):
    total_reward = reward_stochastic_samples(policy, task, gamma, num_trials, budget, tol, **args)
    return np.mean(total_reward)

def reward_stochastic_softmax(policy, task, gamma=0.95, num_trials=100, budget=None, tol=1e-6, entropy=1e-2, callback=None):
    total_reward = reward_stochastic_softmax_samples(policy, task, gamma, num_trials, budget, tol, entropy, callback)
    return np.mean(total_reward)

def qval_stochastic(policy, task, gamma=0.95, num_trials=100, budget=20, **args):
    total_reward = qval_stochastic_samples(policy, task, gamma, num_trials, budget, **args)
    return np.mean(total_reward)

def qval2_stochastic(policy, policy2,task, gamma=0.95, num_trials=100, budget=20, **args):
    total_reward = qval2_stochastic_samples(policy, policy2, task, gamma, num_trials, budget, **args)
    return np.mean(total_reward)

def reward_stochastic_mean_std(policy, task, gamma=0.05, num_trials=100, tol=1e-6, **args):
    total_reward = reward_stochastic_samples(policy, task, gamma, num_trials, tol, **args)
    return (np.mean(total_reward), np.std(total_reward) / np.sqrt(num_trials))

def reward_tabular(policy, task, tol=1e-4):
    '''
    compute exactly expected rewards averaged over start states.
    '''
    policy.task = task # configure the policy task in the multi-task setting.
    V = np.zeros(task.get_num_states())
    while True:
        # repeatedly perform reward bootstrapping on each state
        # given actions produced from the policy.
        max_diff = 0.

        # TODO: Add priority sweeping for state in xrange(self.num_states):
        for state in task.get_valid_states():
            if not policy.is_tabular():
                state_vector = task.wrap_stateid(state)
                poss_actions = policy.get_action_distribution(state_vector, method='eps-greedy', epsilon=0.01)
                # poss_actions = policy.get_action_distribution(state_vector, method='softmax', temperature=5e-2)
            else:
                poss_actions = policy.get_action_distribution(state)


            total_val = 0.
            for action, action_prob in poss_actions.items():
                val = 0.
                ns_dist = task.next_state_distribution(state, action)
                for ns, prob in ns_dist:
                    val += prob * (task.get_reward(state, action, ns) +
                                    task.gamma * V[ns])
                total_val += action_prob * val

            diff = abs(V[state] - total_val)
            V[state] = total_val

            if diff > max_diff:
                max_diff = diff

        if max_diff < tol:
            break
    return V

def expected_reward_tabular(policy, task, tol=1e-4):
    '''
    compute exactly expected rewards averaged over start states.
    '''
    V = reward_tabular(policy, task, tol)
    rewards = [V[state] for state in task.get_valid_states()]
    return np.mean(rewards)

def expected_reward_tabular_normalized(policy, task, tol=1e-4):
    '''
    compute the expected reward / reward by value iteration
    averaged over states.
    '''
    gtV = compute_tabular_value(task, tol) # ground truth values by value iteration.
    V = reward_tabular(policy, task, tol)
    rewards = [V[state] / gtV[state] for state in task.get_valid_states()]
    return np.mean(rewards)

def reward_tabular_normalized(policy, task, tol=1e-4):
    '''
    compute the expected reward / reward by value iteration
    averaged over states.
    '''
    gtV = compute_tabular_value(task, tol) # ground truth values by value iteration.
    V = reward_tabular(policy, task, tol)
    return V / gtV

def reward_tabular_normalized_fix_start(policy, task, tol=1e-4):
    '''
    compute the expected reward / reward by value iteration
    averaged over states.
    '''
    states = [task.start_state]
    gtV = compute_tabular_value(task, tol) # ground truth values by value iteration.
    V = reward_tabular(policy, task, tol)
    rewards = {state: V[state] / gtV[state] for state in task.get_valid_states()}
    return np.mean([rewards[state] for state in states])

def eval_dataset(policy, tasks, method=expected_reward_tabular_normalized):
    reward = 0.0
    for task in tasks:
        reward += method(policy, task, tol=1e-4)
    return reward / len(tasks)


