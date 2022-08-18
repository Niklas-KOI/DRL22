#!/usr/bin/env python
# Four spaces as indentation [no tabs]

import unittest
from action import Action
from propositional_planner import Propositional_Planner
import os

# ==========================================
# Test Propositional_Planner
# ==========================================

class Test_Propositional_Planner(unittest.TestCase):

    # ------------------------------------------
    # Test solve
    # ------------------------------------------

    def test_solve_dinner(self):
        planner = Propositional_Planner()
        self.assertEqual(planner.solve('dinner/dinner.pddl', 'dinner/pb1.pddl'),
            [
                Action('cook', [], [['clean']], [], [['dinner']], []),
                Action('wrap', [], [['quiet']], [], [['present']], []),
                Action('carry', [], [['garbage']], [], [], [['garbage'], ['clean']])
            ]
        )

    #-------------------------------------------
    # Split propositions
    #-------------------------------------------

if __name__ == '__main__':
    prob = ''
    with open('prob.pddl', 'r') as f:
        prob = f.read()
    dom = ''
    with open('domain.pddl', 'r') as f:
        dom = f.read()
    planner = Propositional_Planner()
    actions = planner.solve(dom, prob)
    print(actions)
    # unittest.main()