import yaml
import argparse
import numpy as np
import flwr as fl

from flwr.server.strategy import FedAdagrad, FedAdam, FedAvg, FedYogi
from flwr_baselines.experiments.adaptive_federated_optimization.cifar10.client import (
    CifarRayClient,
    get_eval_fn,
    get_resnet18_gn,
    transforms_test,
)
from pathlib import Path
from torchvision.datasets import CIFAR10
from typing import Dict
from utils import partition_and_save, torch_model_to_parameters


def main(config):
    fed_dir = Path(config.root_dir) / "partitions" / f"{config.lda_concentration:.2f}"

    # Create Partitions
    trainset = CIFAR10(root=config.root_dir, train=True, download=True)
    flwr_trainset = (trainset.data, np.array(trainset.targets, dtype=np.long))
    partition_and_save(
        dataset=flwr_trainset,
        fed_dir=Path(fed_dir),
        dirichlet_dist=None,
        num_partitions=config.total_num_clients,
        concentration=config.lda_concentration,
    )

    # Download testset for centralized evaluation
    testset = CIFAR10(
        root="./data", train=False, download=True, transform=transforms_test
    )

    # Define client resources and ray configs
    client_resources = {"num_cpus": config.cpus_per_client}
    ray_config = {"include_dashboard": config.ray_config.include_dashboard}

    def client_fn(cid: str):
        # create a single client instance
        return CifarRayClient(cid, fed_dir)

    # Helper functions

    model = get_resnet18_gn()
    initial_parameters = torch_model_to_parameters(model)

    for current_strategy in [FedAdagrad, FedAdam, FedYogi, FedAvg]:

        def fit_config(rnd: int) -> Dict[str, str]:
            """Return a configuration with specific client learning rate."""
            local_config = {
                "epoch_global": str(rnd),
                "epochs": str(config.epochs_per_round),
                "batch_size": str(config.batch_size),
                "client_learning_rate": strategy.eta_l,
            }
            return local_config

        strategy = current_strategy(
            fraction_fit=float(config.num_clients_per_round).num_clients,
            min_fit_clients=config.num_clients_per_round,
            min_available_clients=config.num_clients,
            on_fit_config_fn=fit_config,
            eval_fn=get_eval_fn(testset),
            initial_parameters=initial_parameters,
        )

        # start simulation
        fl.simulation.start_simulation(
            client_fn=client_fn,
            num_clients=config.num_clients,
            client_resources=client_resources,
            num_rounds=config.num_rounds,
            strategy=strategy,
            ray_init_args=ray_config,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run CIFAR10 experiments for Adaptive Federated Optimization."
    )
    parser.add_argument(
        "--config",
        type=str,
        required=True,
        default="./configs/default.yaml",
        help="path to yaml file containing experiments parameters (default:'./configs/default.yaml').",
    )
    args = parser.parse_args()
    with open("args.config", "r") as config_file:
        try:
            config = yaml.safe_load(config_file)
        except yaml.YAMLError as exc:
            print(exc)
            print("Please check your config file.")

    main(config)
