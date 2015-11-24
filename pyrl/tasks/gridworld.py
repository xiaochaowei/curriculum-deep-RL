from pyrl.tasks.task import Task

import random
import numpy as np
import matplotlib.pyplot as plt

class GridWorld(Task):
    ''' RL variant of gridworld where the dynamics and reward function are not
        fully observed

        Currently, this task is episodic. If an agent reaches one of the
        reward states, it receives the reward and is reset to a new starting
        location.
    '''
    N = (0, 1)
    E = (1, 0)
    W = (-1, 0)
    S = (0, -1)

    actions = [N, E, W, S]

    def __init__(self, grid, action_stoch, goal, rewards, wall_penalty):
        ''' grid is a 2D numpy array with 0 indicates where the agent
            can pass and 1 indicates an impermeable wall.

            action_stoch is the percentage of time
            environment makes a random transition
            '''
        self.grid = grid
        self.action_stoch = action_stoch
        self.goal = dict(goal)
        self.free_pos = self._free_pos()
        self.curr_pos = random.choice(self.free_pos)
        self.hit_wall = False

        self.wall_penalty = wall_penalty
        self.rewards = dict(rewards)
        self.env = grid

        # save initial state
        self.init_goal = dict(goal)
        self.init_rewards = dict(rewards)

        # start the game fresh.
        self.reset()

    def _free_pos(self):
        pos = []
        self.state_id = {}
        self.state_pos = {}
        state_num = 0
        w, h = self.grid.shape
        for i in xrange(w):
            for j in xrange(h):
                if self.grid[i][j] == 0. and (i, j) not in self.goal:
                    pos.append((i, j))
                    self.state_id[(i, j)] = state_num
                    self.state_pos[state_num] = (i, j)
                    state_num += 1
        return pos

    def reset(self):
        self.hit_wall = False
        self.curr_pos = random.choice(self.free_pos)
        self.goal = dict(self.init_goal)
        self.rewards = dict(self.init_rewards)
        (h, w) = self.grid.shape
        self.state_3d = np.zeros((3, h, w))
        self.state_3d[0, self.curr_pos[0], self.curr_pos[1]] = 1.
        for pos in self.goal:
            self.state_3d[1, pos[0], pos[1]] = 1.
        self.state_3d[2, :, :] = self.grid

    @property
    def curr_state(self):
        '''
        state is a 3xHxW tensor [state, goal, wall]
        should deep copy the state as it will go into the experience buffer.
        '''
        return np.array(self.state_3d)

    @property
    def num_states(self):
        w, h = self.grid.shape
        return w * h

    @property
    def state_shape(self):
        return self.state_3d.shape

    @property
    def shape(self):
        return self.grid.shape

    @property
    def num_actions(self):
        return len(self.actions)

    @property
    def valid_actions(self):
        return range(len(self.actions))

    def _move(self, state, act):
        return (state[0] + act[0], state[1] + act[1])

    def _out_of_bounds(self, state):
        return state[0] < 0 or state[0] >= self.grid.shape[0] or state[1] < 0 \
            or state[1] >= self.grid.shape[1] or self.grid[state[0], state[1]]

    def step(self, action):
        reward = 0.

        # update state_3d matrix
        self.state_3d[0, self.curr_pos[0], self.curr_pos[1]] = 0.

        # compute new coordinate.
        if random.random() < self.action_stoch:
            tmp = self._move(self.curr_pos, random.choice(self.actions))
        else:
            tmp = self._move(self.curr_pos, self.actions[action])
        if self._out_of_bounds(tmp):
            self.hit_wall = True
        else:
            self.hit_wall = False
            self.curr_pos = tmp

        # update state_3d matrix.
        self.state_3d[0, self.curr_pos[0], self.curr_pos[1]] = 1.

        # update goal.
        if self.curr_pos in self.goal:
            self.state_3d[1, self.curr_pos[0], self.curr_pos[1]] = 0.
            reward = float(self.rewards[self.curr_pos])
            del self.goal[self.curr_pos]
            del self.rewards[self.curr_pos]

        return reward

    def is_end(self):
        return len(self.goal) == 0

    def visualize(self, fname = None):
        fig = plt.figure(1, figsize=(5,5))
        plt.clf()
        ax = fig.add_axes([0.0, 0.0, 1., 1.])
        plt.imshow(np.transpose(self.grid), interpolation='none', vmax=1.0, vmin=0.0, aspect='auto')
        for g in self.goal.keys():
            circle = plt.Circle(g, radius=.3, color='w')
            ax.add_artist(circle)
        (x, y) = self.curr_pos
        y = self.grid.shape[0] - 1 - y
        x /= float(self.grid.shape[1])
        y /= float(self.grid.shape[0])
        axicon = fig.add_axes([x, y, 1. / self.grid.shape[1], 1. / self.grid.shape[0]])
        im = plt.imread(__file__[:__file__.rfind('/')] + '/pacman.png')
        axicon.imshow(im, interpolation='nearest')
        axicon.axis('off')
        ax.axis('off')
        if fname:
            plt.savefig(fname)
        else:
            plt.show()


class GridWorldFixedStart(GridWorld):
    def __init__(self, start_pos, grid, action_stoch, goal, rewards, wall_penalty):
        self.start_pos = start_pos
        GridWorld.__init__(self, grid, action_stoch, goal, rewards, wall_penalty)
        assert(start_pos in self.free_pos)

    def reset(self):
        GridWorld.reset(self)
        self.state_3d[0, self.curr_pos[0], self.curr_pos[1]] = 0.
        self.curr_pos = self.start_pos
        self.state_3d[0, self.curr_pos[0], self.curr_pos[1]] = 1.

    def __repr__(self):
        return str(self.start_pos) + ' -> ' + ','.join([str(key) for key in self.goal.keys()])

