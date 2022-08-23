import subprocess
import os
from typing import Tuple
import unittest
from torch import Tensor
import torch
from bastionai.client import Connection, SGD  # type: ignore [import]
from torch.nn import Module
from bastionai.psg.nn import Linear  # type: ignore [import]
from torch.utils.data import DataLoader

import logging
from bastionai.utils import TensorDataset  # type: ignore [import]
from server import launch_server  # type: ignore [import]

logging.basicConfig(level=logging.INFO)


class LinRegTest(unittest.TestCase):
    def test_model_and_data_upload(self):
        with Connection("localhost", 50051, default_secret=b"") as client:
            remote_dataloader = client.RemoteDataLoader(
                train_dataloader,
                test_dataloader,
                "Dummy 1D Linear Regression Dataset (param is 2)",
            )
            remote_learner = client.RemoteLearner(
                lreg_model,
                remote_dataloader,
                metric="l2",
                optimizer=SGD(lr=0.1),
                model_description="1D Linear Regression Model",
                expand=False,
            )

        self.assertEqual(remote_learner.client, client)

    def test_weights_before_and_after_upload(self):
        with Connection("localhost", 50051, default_secret=b"") as client:
            remote_dataloader = client.RemoteDataLoader(
                train_dataloader,
                test_dataloader,
                "Dummy 1D Linear Regression Dataset (param is 2)",
            )
            remote_learner = client.RemoteLearner(
                lreg_model,
                remote_dataloader,
                metric="l2",
                optimizer=SGD(lr=0.1),
                model_description="1D Linear Regression Model",
                expand=False,
            )

            bastion_lreg_model = remote_learner.get_model()
        self.assertEqual(bastion_lreg_model, lreg_model)


def setUpModule():
    global train_dataloader, test_dataloader, lreg_model

    launch_server()

    class LReg(Module):
        def __init__(self) -> None:
            super().__init__()
            self.fc1 = Linear(1, 1, 2)

        def forward(self, x: Tensor) -> Tensor:
            return self.fc1(x)

    lreg_model = LReg()
    
    X = torch.tensor([[0.0], [1.0], [0.5], [0.2]])
    Y = torch.tensor([[0.0], [2.0], [1.0], [0.4]])
    train_dataset = TensorDataset([X], Y)
    train_dataloader = DataLoader(train_dataset, batch_size=2)

    X = torch.tensor([[0.1], [-1.0]])
    Y = torch.tensor([[0.2], [-2.0]])
    test_dataset = TensorDataset([X], Y)
    test_dataloader = DataLoader(test_dataset, batch_size=2)


if __name__ == "__main__":
    unittest.main()
