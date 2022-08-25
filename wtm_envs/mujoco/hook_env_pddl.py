import numpy as np
from baselines.her_pddl.pddl.propositional_planner import Propositional_Planner
from gym.envs.robotics import rotations
import time
from wtm_envs.mujoco.pddl_env import PDDLEnv


class PDDLHookEnv(PDDLEnv):
    grip_open_threshold = [0.038, 1.0]
    grip_closed_threshold = [0.0, 0.025]
    distance_threshold = 0.02
    grasp_z_offset = 0.005
    rake_handle_x_offset = 2 * (0.125 - 0.01)
    at_x_offset = 0.025
    at_y_offset = 0.03
    on_z_offset = 0.05
    table_height = 0.5
    obj_height = 0.05

    def __init__(self, n_objects):
        self.n_objects = n_objects
        assert n_objects in [1,2], "At most one object allowed at this time."
        PDDLEnv.__init__(self)

    def _gen_pred_functs(self):
        self.pred2subg_functs = {}
        self.obs2pred_functs = {}

        def make_gripper_at_o_functs(o_idx):

            def _pred2subg_function(obs, goal):
                o_pos = self.get_o_pos(obs, o_idx)
                gripper_tgt_pos = o_pos.copy()
                if o_idx == 0:  # if the hook, assuming that the hook position returned from the environment is at the tip
                    # gripper_tgt_pos[0] -= ROT.rake_handle_x_offset  # the hook is 0.2 m long in x-axis
                    o_rot = self.get_o_rot(obs, o_idx, self.n_objects)  # TODO: check n_objects
                    handle_offset = self.compute_handle_pos(o_pos, o_rot)
                    gripper_tgt_pos += handle_offset
                gripper_tgt_pos[2] += self.grasp_z_offset
                subg = [0] + list(gripper_tgt_pos)
                return subg

            def _obs2pred_function(obs, goal):
                gripper_tgt_pos = _pred2subg_function(obs, goal)[1:]
                gripper_pos = obs[0:3]
                distance = np.linalg.norm(gripper_pos - gripper_tgt_pos)
                is_true = distance < self.distance_threshold
                return is_true

            return _pred2subg_function, _obs2pred_function

        for o in range(self.n_objects):
            pred_name = 'gripper_at_o{}'.format(o)
            self.pred2subg_functs[pred_name], self.obs2pred_functs[pred_name] = make_gripper_at_o_functs(o)

        def make_o_at_o_functs(o1_idx, o2_idx):
            def _pred2subg_function(obs, goal):
                o2_pos = self.get_o_pos(obs, o2_idx)
                x_offset = self.at_x_offset
                o1_pos = self.get_o_pos(obs, o1_idx)
                if o1_pos[1] >= o2_pos[1]:
                    y_offset = +self.at_y_offset
                else:
                    y_offset = -self.at_y_offset
                # if goal[(o2_idx+1)*3+1] >= o2_pos[1]:
                #     y_offset = -self.at_y_offset
                # else:
                #     y_offset = +self.at_y_offset
                o1_tgt_pos = o2_pos + [x_offset, y_offset, 0.]
                subg = [o1_idx + 1] + list(o1_tgt_pos)
                return subg

            def _obs2pred_function(obs, goal):
                tgt_pos = _pred2subg_function(obs, goal)[1:]
                o_pos = self.get_o_pos(obs, o1_idx)
                distance = np.linalg.norm(o_pos - tgt_pos)
                is_true = distance < 4.*self.distance_threshold
                return is_true

            return _pred2subg_function, _obs2pred_function

        for o1 in range(self.n_objects):
            for o2 in range(1, self.n_objects):
                if o1 == o2:
                    continue
                pred_name = 'o{}_at_o{}'.format(o1, o2)
                self.pred2subg_functs[pred_name], self.obs2pred_functs[pred_name] = make_o_at_o_functs(o1, o2)

        def make_gripper_tgt_funct():
            def _pred2subg_function(obs, goal):
                gripper_tgt_pos = goal[0:3]
                subg = [0] + list(gripper_tgt_pos)
                return subg

            def _obs2pred_function(obs, goal):
                tgt_pos = _pred2subg_function(obs, goal)[1:]
                gripper_pos = obs[0:3]
                distance = np.linalg.norm(gripper_pos - tgt_pos)
                is_true = distance < self.distance_threshold
                return is_true

            return _pred2subg_function, _obs2pred_function

        if self.gripper_has_target:
            pred_name = 'gripper_at_target'
            self.pred2subg_functs[pred_name], self.obs2pred_functs[pred_name] = make_gripper_tgt_funct()

        def make_o_at_tgt_functs(o_idx):

            def _pred2subg_function(obs, goal):
                g_pos = self.get_o_goal_pos(goal, o_idx)
                # object_at_target is only true if laying on table.
                # g_pos[2] = self.table_height + self.obj_height
                subg = [o_idx+1] + list(g_pos)
                return subg

            def _obs2pred_function(obs, goal):
                tgt_pos = _pred2subg_function(obs, goal)[1:]
                o_pos = self.get_o_pos(obs, o_idx)
                distance = np.linalg.norm(o_pos - tgt_pos)
                threshold = self.distance_threshold if o_idx == 0 else 1.5*self.distance_threshold
                is_true = distance < threshold
                return is_true

            return _pred2subg_function, _obs2pred_function

        if self.n_objects == 1:
            o_init = 0
        else:
            o_init = 1
        for o in range(o_init, self.n_objects):
            pred_name = 'o{}_at_target'.format(o)
            self.pred2subg_functs[pred_name], self.obs2pred_functs[pred_name] = make_o_at_tgt_functs(o)

    def get_o_pos(self, obs, o_idx):
        start_idx = (o_idx + 1) * 3
        end_idx = start_idx + 3
        o_pos = obs[start_idx:end_idx]
        return o_pos.copy()

    def get_o_rot(self, obs, o_idx, n_objects=2):
        start_idx = (o_idx + 2 + 2 * n_objects) * 3 - 1  # gripper_state has 2 in size
        end_idx = start_idx + 3
        o_rot = obs[start_idx:end_idx]
        return o_rot

    def compute_handle_pos(self, tip_pos, tip_rot):
        rot_mat = rotations.euler2mat(tip_rot)
        tran_mat = np.zeros((4, 4))
        tran_mat[3, 3] = 1.
        tran_mat[:3, 3] = tip_pos
        tran_mat[:3, :3] = rot_mat
        handle = np.zeros((4,))
        # handle[:3] = subgoal[:3]
        handle[0] = -self.rake_handle_x_offset
        # handle[3] = 1.
        handle_new = tran_mat * handle
        return handle_new[:3, 0]

    def get_o_goal_pos(self, goal, o_idx):
        start_idx = (o_idx + 1) * 3
        if self.gripper_has_target is False:
            start_idx -= 3
        end_idx = start_idx + 3
        g_pos = goal[start_idx:end_idx]
        return g_pos

    def gen_actions(self):  # TODO: check
        n_objects = self.n_objects
        actions = []
        not_grasped_str = ''
        for o in range(n_objects):
            not_grasped_str += '(not (grasped_o{}))'.format(o)
        move_gripper_to_o_act_template = \
            "(:action move_gripper_to__o{} \n\t" \
            ":parameters () \n\t" \
            ":precondition () \n\t" \
            ":effect (and (gripper_at_o{}) {} {} (not (gripper_at_target)) )\n)\n\n"
        move_o_to_target_by_o_act_template = \
            "(:action move__o{}_to_target_by__o{} \n\t" \
            ":parameters () \n\t" \
            ":precondition (and (o{}_at_o{}) (gripper_at_o{})) \n\t" \
            ":effect (and (o{}_at_target) (o{}_at_o{}) )\n)\n\n"
        # ":effect (and (o{}_at_target) (o{}_at_o{}) (gripper_at_o{}))\n)\n\n"
        # ":precondition (and (o{}_at_o{}) ) \n\t"
        move_o_to_target_act_template = \
            "(:action move__o{}_to_target \n\t" \
            ":parameters () \n\t" \
            ":precondition (and (gripper_at_o{}) ) \n\t" \
            ":effect (and (o{}_at_target) (gripper_at_o{}))\n)\n\n"
        move_o1_on_o2_act_template = \
            "(:action move__o{}_on__o{}  \n\t" \
            ":parameters () \n\t" \
            ":precondition (and (gripper_at_o{}) ) \n\t" \
            ":effect (and (o{}_on_o{})  {} )\n)\n\n"
        move_o1_at_o2_act_template = \
            "(:action move__o{}_at__o{}  \n\t" \
            ":parameters () \n\t" \
            ":precondition (and (gripper_at_o{}) ) \n\t" \
            ":effect (and (o{}_at_o{}) )\n)\n\n"
        # ":effect (and (o{}_at_o{}) (gripper_at_o{}))\n)\n\n"

        not_o2_at_o_str = ''
        not_elsewhere_str = ''
        for o in range(n_objects):
            # Grasp object action
            # not_o2_at_o_str = ''
            for o2 in range(n_objects):
                if o == o2:
                    continue
                not_o2_at_o_str += ' (not (o{}_at_o{}))'.format(o2, o)  # TODO: check
            # not_elsewhere_str = ''
            for o_other in range(n_objects):
                if o_other == o:
                    continue
                if o_other != 0:
                    not_elsewhere_str += '(not (gripper_at_o{}))'.format(o_other)

        # Move gripper to hook (object0) action --> TODO: check where can grasp the hook
        move_gripper_to_hook_act = move_gripper_to_o_act_template.format(0, 0, not_elsewhere_str, not_o2_at_o_str)
        actions.append(move_gripper_to_hook_act)

        if n_objects >= 2:
            # Move the hook to the cube (object1) action.
            # This is to place the first object on the ground on which other objects will be stacked.
            # move_hook_to_o_act = move_o1_at_o2_act_template.format(0, 1, 0, 0, 1, 0)
            move_hook_to_o_act = move_o1_at_o2_act_template.format(0, 1, 0, 0, 1)
            actions.append(move_hook_to_o_act)

            # Move o to target action.
            # This is to place the cube on the ground at the target position
            # move_o_to_target_act = move_o_to_target_by_o_act_template.format(1, 0, 0, 1, 0, 1, 0, 1, 0)
            # move_o_to_target_act = move_o_to_target_by_o_act_template.format(1, 0, 0, 1, 1, 0, 1, 0)
            move_o_to_target_act = move_o_to_target_by_o_act_template.format(1, 0, 0, 1, 0, 1, 0, 1)
            actions.append(move_o_to_target_act)

            move_hook_to_target_act = move_o_to_target_act_template.format(0, 0, 0, 0)
            actions.append(move_hook_to_target_act)
        else:
            move_o_to_target_act = move_o_to_target_act_template.format(0, 0, 0, 0)
            actions.append(move_o_to_target_act)

        # This is to place the hook to its target position  --> TODO: check if necessary
        # move_hook_to_target_act = move_o_to_target_template.format(0, 0, 1, 0)
        # actions.append(move_hook_to_target_act)

        not_elsewhere_str = ''
        for o in range(n_objects):
            not_elsewhere_str += '(not (gripper_at_o{}))'.format(o)
        move_gripper_to_target = \
            "(:action move_gripper_to_target \n\t" \
            ":parameters () \n\t" \
            ":precondition (and {}) \n\t" \
            ":effect (and (gripper_at_target) {})\n)\n\n".format(not_grasped_str, not_elsewhere_str)

        actions.append(move_gripper_to_target)
        return actions