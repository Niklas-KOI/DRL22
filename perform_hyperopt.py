from hyperopt import fmin, tpe, hp, STATUS_OK, Trials
import pickle
import os
import subprocess
import numpy as np
import time


n_cpu = 16
# min_th = 2
# max_th = 4
# n_ro = 4
n_epochs = 50
# n_train_ro_cycles = 50
# rs = 'future'
# mao = 1

def exec_comm_args(command_args):
    process = subprocess.Popen(command_args, stdout=subprocess.PIPE)
    all_out = ""
    while True:
        output = str(process.stdout.readline()).strip()[2:-3]
        if output == '' and process.poll() is not None:
            break
        if output:
            o = output.strip()
            all_out += o +"\n"
            print(o)
    rc = process.poll()
    return all_out

def test_objective(space_sample):
    print(space_sample)
    evals_per_run = 1

    penalty_magnitude = int(space_sample['penalty_magnitude'])
    test_subgoal_perc = float(space_sample['test_subgoal_perc'])
    cmd_arr = ['./run_hyperopt_single_trial.sh', str(penalty_magnitude), str(round(test_subgoal_perc,3))]
    print(cmd_arr)
    results = []
    for _ in range(evals_per_run):
        # try:
        result = exec_comm_args(cmd_arr)
        print("Done executing hyperopt run.")
        time.sleep(10)
        res_str = str(result).split("--------------------------------------")[-2]
        trial_value = res_str.split("test_0/success_rate")[1]
        trial_value = trial_value.split("|")[1]
        trial_value = float(trial_value)

        print("New score for {}: {}".format(cmd_arr, trial_value))
        time.sleep(5)
        results.append(trial_value)


    res_cost = -np.mean(results)
    print("Final average cost for {}: {}".format(cmd_arr, res_cost))
    return res_cost


if __name__ == '__main__':

    space = {}

    space['penalty_magnitude'] = hp.quniform('penalty_magnitude', 10, 50, 10)
    space['test_subgoal_perc'] = hp.quniform('test_subgoal_perc', 0.2, 0.8, 0.2)
    # space['model_lr'] = hp.loguniform('model_lr', np.log2(0.1), np.log2(10))
    # space['action_selection'] = hp.choice('action_selection', ['random', 'max_pred_surprise'])

    trials_fname = "hyperopt_herhrl_{}.pkl"
    max_parallel = 10

    trials = None
    this_trials_fname = 'trials.pkl'
    # for i in range(max_parallel):
    #     this_trials_fname = trials_fname.format(i)
    #     if os.path.isfile(this_trials_fname) and not os.path.isfile(this_trials_fname+'.used'):
    #         trials = pickle.load(open(this_trials_fname, "rb"))
    #         print("Resuming trials {}".format(this_trials_fname))
    #         # Make file unavailable for other processes that have been started in parallel by creating an empty file
    #         open(this_trials_fname+'.used', 'a').close()
    #         break
    if trials is None:
        for i in range(max_parallel):
            this_trials_fname = trials_fname.format(i)
            if not os.path.isfile(this_trials_fname) and not os.path.isfile(this_trials_fname+'.used'):
                open(this_trials_fname + '.used', 'a').close()
                print("Starting trials {}".format(this_trials_fname))
                break
        trials = Trials()

    runs = 3000
    r = 0
    while r < runs:
        r += 1
        best = fmin(test_objective,
                    space=space,
                    algo=tpe.suggest,
                    trials=trials,
                    max_evals=r,
                    verbose=1)
        print("Performed {} of {} runs.".format(r, runs))
        pickle.dump(trials, open(this_trials_fname, "wb"))
        print(best)
        # print(trials)
    print("done!")
