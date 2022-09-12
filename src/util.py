import os
import subprocess
import sys
import importlib
import inspect
import functools
import tensorflow as tf
import numpy as np
# from baselines.common import tf_util as U
import re

# ================================================================
# Flat vectors
# ================================================================

def var_shape(x):
    out = x.get_shape().as_list()
    assert all(isinstance(a, int) for a in out), \
        "shape function assumes that shape is fully known"
    return out

def numel(x):
    return intprod(var_shape(x))

def intprod(x):
    return int(np.prod(x))

def store_args(method):
    """Stores provided method args as instance attributes.
    """
    argspec = inspect.getfullargspec(method)
    defaults = {}
    if argspec.defaults is not None:
        defaults = dict(
            zip(argspec.args[-len(argspec.defaults):], argspec.defaults))
    if argspec.kwonlydefaults is not None:
        defaults.update(argspec.kwonlydefaults)
    arg_names = argspec.args[1:]

    @functools.wraps(method)
    def wrapper(*positional_args, **keyword_args):
        self = positional_args[0]
        # Get default arg values
        args = defaults.copy()
        # Add provided arg values
        for name, value in zip(arg_names, positional_args[1:]):
            args[name] = value
        args.update(keyword_args)
        self.__dict__.update(args)
        return method(*positional_args, **keyword_args)

    return wrapper

def get_subdir_by_params(path_params, ctr=0):
    param_strs = []

    def shorten_split_elem(elem_str, chars_to_split):
        split_elems = elem_str.split(chars_to_split[0])
        short_split_elem_strs = []
        for split_elem in split_elems:
            if len(chars_to_split) == 1:
                if split_elem.find("_") == -1:
                    short_split_elem = str(split_elem)
                else:
                    short_split_elem = "_".join([us_elem[:2] for us_elem in split_elem.split("_")])
            else:
                short_split_elem = shorten_split_elem(split_elem, chars_to_split[1:])
            short_split_elem_strs.append(short_split_elem)
        short_ret_str = chars_to_split[0].join(short_split_elem_strs)
        return short_ret_str

    for p,v in sorted(path_params.items()):
        if str(v) == '':
            continue
        this_key_str = "".join([s[:3] for s in p.split("_")])
        chars_to_split = [",", ":", "[", "]"]
        this_v_str = shorten_split_elem(str(v), chars_to_split)
        this_param_str = '{}:{}'.format(this_key_str, this_v_str)
        param_strs.append(this_param_str)

    subdir_str = "|".join(param_strs)
    subdir_str += "|" + str(ctr)

    # param_subdir = "_".join(
    #     ['{}:{}'.format("".join([s[:2] for s in p.split("_")]), str(v).split(":")[-1]) for p, v in
    #      sorted(path_params.items()) if str(v) != '']) + "_" + str(ctr)
    return subdir_str

def get_git_label():
    try:
        git_label = str(subprocess.check_output(["git", 'describe', '--always'])).strip()[2:-3]
    except:
        git_label = ''
    return git_label

def import_function(spec):
    """Import a function identified by a string like "pkg.module:fn_name".
    """
    mod_name, fn_name = spec.split(':')
    module = importlib.import_module(mod_name)
    fn = getattr(module, fn_name)
    return fn

def flatten_grads(var_list, grads):
    """Flattens a variables and their gradients.
    """
    if len(var_list) == 0:
        return []
    try:
        grad_list = [tf.reshape(grad, [numel(v)]) for (v, grad) in zip(var_list, grads)]
    except Exception as e:
        print(e)
    grad_list = [tf.reshape(grad, [numel(v)]) for (v, grad) in zip(var_list, grads)]
    return tf.concat(grad_list, 0)

def flatten_grads_compact(var_list, grads):
    """Flattens a variables and their gradients.
    """
    if len(var_list) == 0:
        return []
    return tf.concat([tf.reshape(grad, [numel(v)])
                      for (v, grad) in zip(var_list, grads)], 0)


def nn(input, layers_sizes, reuse=None, flatten=False, name=""):
    """Creates a simple neural network
    """
    for i, size in enumerate(layers_sizes):
        activation = tf.nn.relu if i < len(layers_sizes) - 1 else None
        input = tf.layers.dense(inputs=input,
                                units=size,
                                kernel_initializer=tf.contrib.layers.xavier_initializer(),
                                reuse=reuse,
                                name=name + '_' + str(i))
        if activation:
            input = activation(input)
    if flatten:
        assert layers_sizes[-1] == 1
        input = tf.reshape(input, [-1])
    return input


def critic_nn(input, layers_sizes, q_limit, reuse=None, flatten=False, name=""):
    ret_nn = nn(input, layers_sizes, reuse=reuse, flatten=flatten, name=name)
    q_init = -0.067
    # q_limit = q_limit
    q_offset = -np.log(q_limit / q_init - 1)
    output = tf.sigmoid(ret_nn + q_offset) * q_limit
    return output


def install_mpi_excepthook():
    import sys
    from mpi4py import MPI
    old_hook = sys.excepthook

    def new_hook(a, b, c):
        old_hook(a, b, c)
        sys.stdout.flush()
        sys.stderr.flush()
        MPI.COMM_WORLD.Abort()
    sys.excepthook = new_hook


def mpi_fork(n, extra_mpi_args=[]):
    """Re-launches the current script with workers
    Returns "parent" for original parent, "child" for MPI children
    """
    if n <= 1:
        return "child"
    if os.getenv("IN_MPI") is None:
        env = os.environ.copy()
        env.update(
            MKL_NUM_THREADS="1",
            OMP_NUM_THREADS="1",
            IN_MPI="1"
        )
        # "-bind-to core" is crucial for good performance
        args = ["mpirun", "-np", str(n)] + \
            extra_mpi_args + \
            [sys.executable]

        args += sys.argv
        ret = subprocess.check_call(args, env=env)
        print(ret)
        return "parent"
    else:
        install_mpi_excepthook()
        return "child"


def convert_episode_to_batch_major(episode):
    """Converts an episode to have the batch dimension in the major (first)
    dimension.
    """
    episode_batch = {}
    for key in episode.keys():
        val = np.array(episode[key]).copy()
        # make inputs batch-major instead of time-major
        episode_batch[key] = val.swapaxes(0, 1)

    return episode_batch


def transitions_in_episode_batch(episode_batch):
    """Number of transitions in a given episode batch.
    """
    shape = episode_batch['u'].shape
    return shape[0] * shape[1]


def reshape_for_broadcasting(source, target):
    """Reshapes a tensor (source) to have the correct shape and dtype of the target
    before broadcasting it with MPI.
    """
    dim = len(target.get_shape())
    shape = ([1] * (dim - 1)) + [-1]
    return tf.reshape(tf.cast(source, target.dtype), shape)

def prob_dist2discrete(prob_dist):
    discrete = np.argmax(prob_dist, axis=-1)
    # discrete = np.reshape(discrete, newshape=(prob_dist.shape[0],-1))
    return discrete


def physical_cpu_core_count():
    try:
        res = open('/proc/cpuinfo').read()
        idx = res.find('cpu cores') + len("cpu cores")
        idx = res.find(": ", idx) + len(": ")
        nl_idx = res.find("\n", idx)
        res = res[idx:nl_idx]
        res = int(res)

        if res > 0:
            return res
    except IOError:
        return 0
        pass

