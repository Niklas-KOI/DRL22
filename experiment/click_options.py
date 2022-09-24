import click
import importlib


_global_options = [
    click.option(
        "--env",
        type=str,
        default="AntFourRoomsEnv-v0",
        help="the name of the OpenAI Gym environment that you want to train on. E.g. TowerBuildMujocoEnv-sparse-gripper_random-o2-h1-2-v1, AntFourRoomsEnv-v0",
    ),
    click.option(
        "--algorithm",
        default="src.chac",
        help="the name of the algorithm to be used",
        type=click.Choice(["src.chac"]),
    ),
    click.option(
        "--base_logdir",
        type=str,
        default="data",
        help="the path to where logs and policy pickles should go. If not specified, creates a folder in /tmp/",
    ),
    click.option(
        "--n_epochs",
        type=int,
        default=300,
        help="the max. number of training epochs to run",
    ),
    click.option(
        "--num_cpu",
        type=int,
        default=1,
        help="the number of CPU cores to use (using MPI)",
    ),
    click.option(
        "--seed",
        type=int,
        default=0,
        help="the random seed used to seed both the environment and the training code",
    ),
    click.option(
        "--policy_save_interval",
        type=int,
        default=10,
        help="the interval with which policy pickles are saved. If set to 0, only the best and latest policy will be pickled.",
    ),
    click.option(
        "--restore_policy",
        type=str,
        default=None,
        help="The pretrained policy file to start with to avoid learning from scratch again. Useful for interrupting and restoring training sessions.",
    ),
    click.option(
        "--rollout_batch_size",
        type=int,
        default=1,
        help="The number of simultaneous rollouts.",
    ),
    click.option(
        "--n_train_rollouts",
        type=int,
        default=100,
        help="The number of training episodes (parallel rollouts) per epoch.",
    ),
    click.option(
        "--render",
        type=int,
        default=0,
        help="Whether or not to render the rollout execution.",
    ),
    click.option(
        "--max_try_idx",
        type=int,
        default=199,
        help="Max. number of tries for this training config.",
    ),
    click.option(
        "--try_start_idx", type=int, default=100, help="Index for first try."
    ),
    click.option(
        "--early_stop_threshold",
        type=float,
        default=100,
        help="The early stopping threshold.",
    ),
    click.option(
        "--early_stop_data_column",
        type=str,
        default="test/success_rate",
        help="The data column on which early stopping is based.",
    ),
    click.option(
        "--info",
        type=str,
        default="",
        help="A command line comment that will be integrated in the folder where the results are stored. Useful for debugging and addressing temporary changes to the code..",
    ),
    click.option(
        "--bind_core",
        type=int,
        default=0,
        help="Whether to bind each MPI worker to a core.",
    ),
    click.option(
        "--graph",
        type=int,
        default=1,
        help="Whether or not to create the graph.",
    ),
    # For regularization
    click.option(
        "--regularization",
        type=bool,
        help="Enable regularization of the subgoal representation",
    ),
]


@click.command(
    context_settings=dict(
        ignore_unknown_options=True,
        allow_extra_args=True,
    )
)
@click.pass_context
def get_policy_click(ctx, **kwargs):
    policy_linker = importlib.import_module(
        kwargs["algorithm"] + ".interface.click_options", package=__package__
    )
    policy_args = ctx.forward(policy_linker.get_click_option)
    return policy_args


def import_creator(library_path):
    config = importlib.import_module(
        library_path + ".interface.config", package=__package__
    )
    RolloutWorker = getattr(
        importlib.import_module(library_path + ".rollout", package=__package__),
        "RolloutWorker",
    )
    return config, RolloutWorker


def click_main(func):
    for option in reversed(_global_options):
        func = option(func)
    return func
