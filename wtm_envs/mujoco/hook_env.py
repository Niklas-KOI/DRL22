import numpy as np
import random

from gym.envs.robotics import rotations
from wtm_envs.mujoco import robot_env, utils
from mujoco_py.generated import const as mj_const
from wtm_envs.mujoco.hook_env_pddl import *
from wtm_envs.mujoco.wtm_env import goal_distance
from wtm_envs.mujoco.wtm_env import WTMEnv
from wtm_envs.mujoco.hook_env_pddl import PDDLHookEnv
import mujoco_py


class HookEnv(WTMEnv, PDDLHookEnv):
    """Superclass for all Hook environments.
    """

    def __init__(
        self, model_path, n_substeps, gripper_extra_height, block_gripper,
            target_in_the_air, target_offset, obj_range, target_range,
            distance_threshold, initial_qpos, reward_type,
            gripper_goal, n_objects, table_height, obj_height, min_tower_height=None, max_tower_height=None,
            easy=1
    ):
        """Initializes a new Fetch environment.

        Args:
            model_path (string): path to the environments XML file
            n_substeps (int): number of substeps the simulation runs on every call to step
            gripper_extra_height (float): additional height above the table when positioning the gripper
            block_gripper (boolean): whether or not the gripper is blocked (i.e. not movable) or not
            target_in_the_air (boolean): whether or not the target should be in the air above the table or on the table surface
            target_offset (float or array with 3 elements): offset of the target
            obj_range (float): range of a uniform distribution for sampling initial object positions
            target_range (float): range of a uniform distribution for sampling a target
            distance_threshold (float): the threshold after which a goal is considered achieved
            initial_qpos (dict): a dictionary of joint names and values that define the initial configuration
            reward_type ('sparse' or 'dense'): the reward type, i.e. sparse or dense
            gripper_goal ('gripper_none', 'gripper_above', 'gripper_random'): the gripper's goal location
            n_objects (int): no of objects in the environment. If none, then no_of_objects=0
            min_tower_height (int): the minimum height of the tower. (not required)
            max_tower_height (int): the maximum height of the tower. (not required)
        """

        assert n_objects == 2, "Cannot have more than 2 objects for this environment at the time being!"

        self.gripper_extra_height = gripper_extra_height
        self.block_gripper = block_gripper
        self.target_in_the_air = target_in_the_air
        self.target_offset = target_offset
        self.obj_range = obj_range
        self.target_range = target_range
        self.distance_threshold = distance_threshold
        self.reward_type = reward_type

        self.gripper_goal = gripper_goal
        self.n_objects = n_objects
        self.table_height = table_height
        self.obj_height = obj_height
        self.min_tower_height = min_tower_height
        self.max_tower_height = max_tower_height
        self.step_ctr = 0

        self.obs_limits = [None, None]
        self.obs_noise_coefficient = 0.0

        self.plan_cache = {}
        self.goal_hierarchy = {}
        self.goal = []
        self.goal_size = (n_objects * 3)
        self.final_goal = []
        if self.gripper_goal != 'gripper_none':
            self.goal_size += 3
        self.gripper_has_target = (gripper_goal != 'gripper_none')

        self._viewers = {}

        self.easy = easy
        n_actions = 4

        WTMEnv.__init__(self, model_path=model_path, n_substeps=n_substeps, initial_qpos=initial_qpos, n_actions=n_actions)
        PDDLHookEnv.__init__(self, n_objects=self.n_objects)



    def _set_action(self, action):
        assert action.shape == (4,)
        action = action.copy()  # ensure that we don't change the action outside of this scope
        pos_ctrl, gripper_ctrl = action[:3], action[3]

        pos_ctrl *= 0.05  # limit maximum change in position
        rot_ctrl = [1., 0., 1., 0.]  # fixed rotation of the end effector, expressed as a quaternion
        gripper_ctrl = np.array([gripper_ctrl, gripper_ctrl])
        assert gripper_ctrl.shape == (2,)
        if self.block_gripper:
            gripper_ctrl = np.zeros_like(gripper_ctrl)
        action = np.concatenate([pos_ctrl, rot_ctrl, gripper_ctrl])

        # Apply action to simulation.
        utils.ctrl_set_action(self.sim, action)
        utils.mocap_set_action(self.sim, action)
        self.step_ctr += 1

    def _obs2goal(self, obs):
        if len(obs.shape) == 1:
            obs_arr = np.array([obs])
        else:
            obs_arr = obs
        assert len(obs_arr.shape) == 2
        goals = []
        for o in obs_arr:
            if self.gripper_goal != 'gripper_none':
                g = o[:self.goal_size]
            else:
                g = o[3:self.goal_size+3]
            goals.append(g)
        goals = np.array(goals)
        if len(obs.shape) == 1:
            return goals[0]
        else:
            return goals

    def _get_obs(self, grip_pos=None, grip_velp=None):
        # If the grip position and grip velp are provided externally, the external values will be used.
        # This can later be extended to provide the properties of all elements in the scene.
        dt = self.sim.nsubsteps * self.sim.model.opt.timestep
        # positions
        if grip_pos is None:
            grip_pos = self.sim.data.get_site_xpos('robot0:grip')
        if grip_velp is None:
            grip_velp = self.sim.data.get_site_xvelp('robot0:grip') * dt

        robot_qpos, robot_qvel = utils.robot_get_obs(self.sim)
        object_pos, object_rot, object_velp, object_velr = ([] for _ in range(4))
        object_rel_pos = []

        if self.n_objects > 0:
            for n_o in range(self.n_objects):
                oname = 'object{}'.format(n_o)
                this_object_pos = self.sim.data.get_site_xpos(oname)
                # rotations
                this_object_rot = rotations.mat2euler(self.sim.data.get_site_xmat(oname))
                if n_o == 0:
                    hook_handle_pos = self.compute_handle_pos(this_object_pos, this_object_rot)
                    this_object_rot = np.concatenate([this_object_rot, hook_handle_pos])
                # velocities
                this_object_velp = self.sim.data.get_site_xvelp(oname) * dt
                this_object_velr = self.sim.data.get_site_xvelr(oname) * dt
                # gripper state
                this_object_rel_pos = this_object_pos - grip_pos
                this_object_velp -= grip_velp

                object_pos = np.concatenate([object_pos, this_object_pos])
                object_rot = np.concatenate([object_rot, this_object_rot])
                object_velp = np.concatenate([object_velp, this_object_velp])
                object_velr = np.concatenate([object_velr, this_object_velr])
                object_rel_pos = np.concatenate([object_rel_pos, this_object_rel_pos])
        else:
            object_pos = object_rot = object_velp = object_velr = object_rel_pos = np.array(np.zeros(3))

        gripper_state = robot_qpos[-2:]
        gripper_vel = robot_qvel[-2:] * dt  # change to a scalar if the gripper is made symmetric

        obs = np.concatenate([
            grip_pos, object_pos.ravel(), object_rel_pos.ravel(), gripper_state, object_rot.ravel(),
            object_velp.ravel(), object_velr.ravel(), grip_velp, gripper_vel,
        ])

        # obs = np.concatenate([
        #     grip_pos, object_pos.ravel(), object_rel_pos.ravel(), gripper_state, object_rot.ravel()
        # ])

        noisy_obs = self.add_noise(obs.copy(), self.obs_history, self.obs_noise_coefficient)
        achieved_goal = self._obs2goal(noisy_obs)

        obs = {'observation': noisy_obs.copy(), 'achieved_goal': achieved_goal.copy(), 'desired_goal': self.goal.copy(), 'non_noisy_obs': obs.copy()}
        # obs['achieved_goal'] = self._obs2goal(obs['observation'])

        return obs

    # def _viewer_setup(self,mode='human'):
    #     if mode == 'human':
    #         body_id = self.sim.model.body_name2id('robot0:gripper_link')
    #         lookat = self.sim.data.body_xpos[body_id]
    #         for idx, value in enumerate(lookat):
    #             self._viewers[mode].cam.lookat[idx] = value
    #         self._viewers[mode].cam.distance = 2.5
    #         self._viewers[mode].cam.azimuth = 132.
    #         self._viewers[mode].cam.elevation = -14.
    #     elif mode == 'rgb_array':
    #         body_id = self.sim.model.body_name2id('robot0:gripper_link')
    #         lookat = self.sim.data.body_xpos[body_id]
    #         for idx, value in enumerate(lookat):
    #             self._viewers[mode].cam.lookat[idx] = value
    #         self._viewers[mode].cam.distance = 1.
    #         self._viewers[mode].cam.azimuth = 180.
    #         self._viewers[mode].cam.elevation = -40.

    def _render_callback(self):
        # Visualize target.

        sites_offset = (self.sim.data.site_xpos - self.sim.model.site_pos).copy()

        obj_goal_start_idx = 0
        if self.gripper_goal != 'gripper_none':
            gripper_target_site_id = self.sim.model.site_name2id('final_arm_target')
            gripper_goal_site_id = self.sim.model.site_name2id('final_arm_goal')
            gripper_tgt_size = (np.ones(3) * 0.02)
            gripper_tgt_size[1] = 0.05
            self.sim.model.site_size[gripper_target_site_id] = gripper_tgt_size
            self.sim.model.site_size[gripper_goal_site_id] = gripper_tgt_size
            if self.goal != []:
                gripper_tgt_goal = self.goal[0:3] - sites_offset[0]
                self.sim.model.site_pos[gripper_target_site_id] = gripper_tgt_goal
            if self.final_goal != []:
                gripper_tgt_final_goal = self.final_goal[0:3] - sites_offset[0]
                self.sim.model.site_pos[gripper_goal_site_id] = gripper_tgt_final_goal
            obj_goal_start_idx += 3

        for n in range(self.n_objects):
            if n == 0:
                o_tgt_y = 0.08
            else:
                o_tgt_y = 0.02
            o_target_site_id = self.sim.model.site_name2id('target{}'.format(n))
            o_goal_site_id = self.sim.model.site_name2id('goal{}'.format(n))
            o_tgt_size = (np.ones(3) * 0.02)
            o_tgt_size[1] = o_tgt_y
            self.sim.model.site_size[o_target_site_id] = o_tgt_size
            self.sim.model.site_size[o_goal_site_id] = o_tgt_size
            if self.goal != []:
                o_tgt_goal = self.goal[obj_goal_start_idx:obj_goal_start_idx + 3] - sites_offset[0]
                self.sim.model.site_pos[o_target_site_id] = o_tgt_goal
            if self.final_goal != []:
                o_tgt_final_goal = self.final_goal[obj_goal_start_idx:obj_goal_start_idx + 3] - sites_offset[0]
                self.sim.model.site_pos[o_goal_site_id] = o_tgt_final_goal

            obj_goal_start_idx += 3

        self.sim.forward()

    def _reset_sim(self):
        self.step_ctr = 0
        self.sim.set_state(self.initial_state)
        # Randomize start position of objects.
        object_0 = None
        for o in range(self.n_objects):
            oname = 'object{}'.format(o)
            object_xpos = self.initial_gripper_xpos[:2]
            close = True
            while close:
                inner_radius_id = self.sim.model.site_name2id('inner_radius_target')
                outer_radius_id = self.sim.model.site_name2id('outer_radius_target')
                inner_outer_ratio = self.sim.model.site_size[inner_radius_id][0] / \
                                    self.sim.model.site_size[outer_radius_id][0]
                r = self.sim.model.site_size[outer_radius_id][0] * \
                    np.sqrt(np.random.uniform(inner_outer_ratio, 0.7, 1))
                theta = np.random.uniform(-0.1, 0.1, 1) * 2 * np.pi
                x = self.sim.data.get_site_xpos('outer_radius_target')[0] + r * np.cos(theta)
                y = self.sim.data.get_site_xpos('outer_radius_target')[1] + r * np.sin(theta)
                object_xpos = [x,y]

                close = False
                dist_to_nearest = np.linalg.norm(object_xpos - self.initial_gripper_xpos[:2])
                # Iterate through all previously placed boxes and select closest:
                for o_other in range(o):
                    other_xpos = self.sim.data.get_joint_qpos('object{}:joint'.format(o_other))[:2]
                    # Reduce the complexity of the environment by generating the cube very close to the hook
                    if self.easy:
                        if np.random.random() >= 0.5:
                            object_xpos[1] = other_xpos[1] + 0.02
                        else:
                            object_xpos[1] = other_xpos[1] - 0.02
                    dist = np.linalg.norm(object_xpos - other_xpos)
                    dist_to_nearest = min(dist, dist_to_nearest)
                if dist_to_nearest < 0.01:
                    close = True

            object_qpos = self.sim.data.get_joint_qpos('{}:joint'.format(oname))
            assert object_qpos.shape == (7,)
            object_qpos[:2] = object_xpos
            object_qpos[2] = self.table_height + (self.obj_height / 2)
            self.sim.data.set_joint_qpos('{}:joint'.format(oname), object_qpos)
        self.sim.forward()
        return True

    def _sample_goal(self):
        obs = self._get_obs()
        target_goal = None
        if obs is not None:
            if self.gripper_goal != 'gripper_none':
                goal = obs['observation'].copy()[:self.goal_size]
            else:
                goal = obs['observation'].copy()[3:self.goal_size + 3]

            if self.gripper_goal != 'gripper_none' and self.n_objects > 0:
                target_goal_start_idx = 3
            else:
                target_goal_start_idx = 0

            if self.n_objects > 0:
                target_range = self.n_objects
            else:
                target_range = 1
            hook = None
            for n_o in range(target_range):
                # too_close = True
                while True:
                    target_goal = self.initial_gripper_xpos[:3] + self.np_random.uniform(0,
                                                                                         self.target_range,
                                                                                         size=3)
                    sign = 1.
                    oname = 1
                    # if self.easy and self.n_objects >= 2:
                    #     oname = 1
                    #     sign = 1.
                    # else:
                    #     oname = 0
                    #     sign = -1.
                    if self.sim.data.get_joint_qpos('object0:joint')[1] >= self.sim.data.get_joint_qpos('object1:joint')[1]:
                        target_goal[1] = self.sim.data.get_joint_qpos('object{}:joint'.format(oname))[1] \
                                         - sign*self.np_random.uniform(0, self.target_range, size=1)
                    else:
                        target_goal[1] = self.sim.data.get_joint_qpos('object{}:joint'.format(oname))[1] \
                                         + sign*self.np_random.uniform(0, self.target_range, size=1)

                    target_goal += self.target_offset
                    rnd_height = random.randint(self.min_tower_height, self.max_tower_height)
                    self.goal_tower_height = rnd_height # TODO: remove tower_height in rollout for this environment
                    target_goal[2] = self.table_height + (self.obj_height) - (self.obj_height / 2)
                    too_close = False
                    for i in range(0, target_goal_start_idx, 3):
                        other_loc = goal[i:i + 3]
                        dist = np.linalg.norm(other_loc[:2] - target_goal[:2], axis=-1)
                        if dist < 0.01:
                            too_close = True
                    if too_close is False:
                        break

                if hook is not None:    # target_0 is None when n_o = 0: the hook case
                    target_goal[0] = hook[0] - self.np_random.uniform(0.025, 0.035, size=1)
                    if self.sim.data.get_joint_qpos('object0:joint')[1] >= self.sim.data.get_joint_qpos('object1:joint')[1]:
                        target_goal[1] = hook[1] - self.np_random.uniform(0.03, 0.05, size=1)
                    else:
                        target_goal[1] = hook[1] + self.np_random.uniform(0.03, 0.05, size=1)
                else:
                    hook = target_goal

                goal[target_goal_start_idx:target_goal_start_idx + 3] = target_goal.copy()
                target_goal_start_idx += 3

            # Final gripper position
            if self.gripper_goal != 'gripper_none':
                # gripper_goal_pos = goal.copy()[-6:-3]
                if self.gripper_goal == 'gripper_above':
                    gripper_goal_pos = goal.copy()[3:6]  # hook tip position
                    # gripper_goal_pos[0] -= self.sim.data.get_geom_xpos('object0/geom')[0]
                    geom_id = self.sim.model.geom_name2id('object0:geom')
                    gripper_goal_pos[0] -= 2 * (self.sim.model.geom_size[geom_id][0] - 0.01)  # 0.28
                    gripper_goal_pos[2] += (1. * self.obj_height)
                elif self.gripper_goal == 'gripper_random':
                    too_close = True
                    while too_close:
                        gripper_goal_pos = self.initial_gripper_xpos[:3] + \
                                           self.np_random.uniform(-self.target_range,
                                                                  self.target_range, size=3)
                        gripper_goal_pos[0] += self.random_gripper_goal_pos_offset[0]
                        gripper_goal_pos[1] += self.random_gripper_goal_pos_offset[1]
                        gripper_goal_pos[2] += self.random_gripper_goal_pos_offset[2]

                        if np.linalg.norm(gripper_goal_pos - target_goal, axis=-1) >= 0.1:
                            too_close = False
                else:
                    raise Exception('gripper_goal {} is not defined'.format(self.gripper_goal))
                goal[:3] = gripper_goal_pos

            return goal.copy()
        else:
            return []

    # def _is_success(self, achieved_goal, desired_goal):
    #     d = goal_distance(achieved_goal, desired_goal)
    #     return (d < self.distance_threshold).astype(np.float32)

    def _env_setup(self, initial_qpos):
        for name, value in initial_qpos.items():
            self.sim.data.set_joint_qpos(name, value)
        utils.reset_mocap_welds(self.sim)
        self.sim.forward()

        # Move end effector into position.
        gripper_target = np.array([-0.498, 0.005, -0.431 + self.gripper_extra_height]) \
                         + self.sim.data.get_site_xpos('robot0:grip')
        gripper_rotation = np.array([1., 0., 1., 0.])
        self.sim.data.set_mocap_pos('robot0:mocap', gripper_target)
        self.sim.data.set_mocap_quat('robot0:mocap', gripper_rotation)
        for _ in range(10):
            self.sim.step()

        # offset the random goal if gripper random is used
        # self.random_gripper_goal_pos_offset = (0.2, 0.0, 0.0)
        self.random_gripper_goal_pos_offset = (0.0, 0.0, 0.14)

        # Extract information for sampling goals.
        self.initial_gripper_xpos = self.sim.data.get_site_xpos('robot0:grip').copy()
        if self.n_objects > 0:
            self.height_offset = self.sim.data.get_site_xpos('object0')[2]

    def get_scale_and_offset_for_normalized_subgoal(self):
        n_objects = self.n_objects
        obj_height = self.obj_height
        scale_xy = self.target_range
        scale_z = obj_height * n_objects / 2
        scale = np.array([scale_xy, scale_xy, scale_z] * (n_objects + 1))
        offset = np.array(list(self.initial_gripper_xpos) * (n_objects + 1))
        for j, off in enumerate(offset):
            if j == 2:
                offset[j] += self.random_gripper_goal_pos_offset[2]
                if self.gripper_goal == 'gripper_random':
                    scale[j] = self.target_range
            elif (j + 1) % 3 == 0:
                offset[j] += obj_height * n_objects / 2
        if self.gripper_goal == 'gripper_none':
            scale = scale[3:]
            offset = offset[3:]
        return scale, offset

