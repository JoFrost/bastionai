from typing import List, TYPE_CHECKING, Union
from torch.nn import Module
from torch.utils.data import Dataset
import grpc
import torch
from ..pb.bastionlab_torch_pb2 import Empty, Metric, TestConfig, TrainConfig  # type: ignore [import]
from ..pb.bastionlab_pb2 import Reference
from ..pb.bastionlab_torch_pb2_grpc import TorchServiceStub  # type: ignore [import]
from ..errors import GRPCException
from .optimizer_config import *

from .utils import (
    TensorDataset,
    dataset_from_chunks,
    deserialize_weights_to_model,
    serialize_dataset,
    serialize_model,
)


if TYPE_CHECKING:
    from .learner import RemoteLearner
    from ..client import Client
    from .remote_torch import RemoteTensor, RemoteDataset


class BastionLabTorch:
    """BastionLab Torch RPC Handle

    Args:
        stub: The underlying gRPC client for the BastionLab Torch protocol.
    """

    def __init__(
        self,
        client: "Client",
    ):
        self.client = client
        self.stub = TorchServiceStub(client._channel)

    def send_model(
        self,
        model: Module,
        name: str,
        description: str = "",
        chunk_size: int = 4_194_285,
        progress: bool = False,
    ) -> Reference:
        """Uploads a Pytorch module to the BastionLab Torch server.

        This endpoint transforms Pytorch modules into TorchScript modules and sends
        them to the BastionLab Torch server over gRPC.

        Args:
            model: The Pytorch nn.Module to upload.
            name: A name for the module being uploaded.
            description: A string description of the module being uploaded.
            chunk_size: Size of a chunk in the BastionLab Torch gRPC protocol in bytes.

        Returns:
            BastionLab Torch gRPC protocol's reference object.
        """

        self.client.refresh_session_if_needed()

        return GRPCException.map_error(
            lambda: self.stub.SendModel(
                serialize_model(
                    model,
                    name=name,
                    description=description,
                    chunk_size=chunk_size,
                    progress=progress,
                )
            )
        )

    def send_dataset(
        self,
        dataset: Dataset,
        name: str,
        description: str = "",
        privacy_limit: Optional[float] = None,
        chunk_size: int = 4_194_285,
        batch_size: int = 1024,
        train_dataset: Optional[Reference] = None,
        progress: bool = False,
    ) -> Reference:
        """Uploads a Pytorch Dataset to the BastionLab Torch server.

        Args:
            model: The Pytorch Dataset to upload.
            name: A name for the dataset being uploaded.
            description: A string description of the dataset being uploaded.
            chunk_size: Size of a chunk in the BastionLab Torch gRPC protocol in bytes.
            batch_size: Size of a unit of serialization in number of samples,
                        increasing this value may increase serialization throughput
                        at the price of a higher memory consumption.
            train_dataset: metadata, True means this dataset is suited for training,
                   False that it should be used for testing/validating only

        Returns:
            BastionLab Torch gRPC protocol's reference object.
        """

        self.client.refresh_session_if_needed()

        return GRPCException.map_error(
            lambda: self.stub.SendDataset(
                serialize_dataset(
                    dataset,
                    name=name,
                    description=description,
                    chunk_size=chunk_size,
                    batch_size=batch_size,
                    privacy_limit=privacy_limit,
                    train_dataset=train_dataset,
                    progress=progress,
                )
            )
        )

    def fetch_model_weights(self, model: Module, ref: Reference) -> None:
        """Fetches the weights of a distant trained model with a BastionLab Torch gRPC protocol reference
        and loads the weights into the passed model instance.

        Args:
            model: The Pytorch's nn.Module whose weights will be replaced by the fetched weights.
            ref: BastionLab Torch gRPC protocol reference object corresponding to the distant trained model.
        """

        self.client.refresh_session_if_needed()

        chunks = GRPCException.map_error(lambda: self.stub.FetchModule(ref))
        deserialize_weights_to_model(model, chunks)

    def fetch_dataset(self, ref: Union["RemoteDataset", Reference]) -> TensorDataset:
        """Fetches the distant dataset with a BastionLab Torch gRPC protocol reference.

        Args:
            ref: BastionLab Torch gRPC protocol reference object corresponding to the distant dataset.

        Returns:
            A dataset instance built from received data.
        """
        from .remote_torch import RemoteDataset

        self.client.refresh_session_if_needed()
        if isinstance(ref, RemoteDataset):
            ref = Reference(
                identifier=ref.identifier, name="", description="", meta=bytes()
            )
        return dataset_from_chunks(
            GRPCException.map_error(lambda: self.stub.FetchDataset(ref))
        )

    def get_available_models(self) -> List[Reference]:
        """Returns the list of BastionLab Torch gRPC protocol references of all available models on the server."""

        self.client.refresh_session_if_needed()

        return GRPCException.map_error(lambda: self.stub.AvailableModels(Empty())).list

    def get_available_datasets(self) -> List[Reference]:
        """Returns the list of BastionLab Torch gRPC protocol references of all datasets on the server."""

        self.client.refresh_session_if_needed()

        return GRPCException.map_error(
            lambda: self.stub.AvailableDatasets(Empty())
        ).list

    def get_available_devices(self) -> List[str]:
        """Returns the list of devices available on the server."""

        self.client.refresh_session_if_needed()

        return GRPCException.map_error(lambda: self.stub.AvailableDevices(Empty())).list

    def get_available_optimizers(self) -> List[str]:
        """Returns the list of optimizers supported by the server."""

        self.client.refresh_session_if_needed()

        return GRPCException.map_error(
            lambda: self.stub.AvailableOptimizers(Empty())
        ).list

    def train(self, config: TrainConfig) -> Reference:
        """Trains a model with hyperparameters defined in `config` on the BastionLab Torch server.

        Args:
            config: Training configuration that specifies the model, dataset and hyperparameters.
        """

        self.client.refresh_session_if_needed()

        return GRPCException.map_error(lambda: self.stub.Train(config))

    def test(self, config: TestConfig) -> Reference:
        """Tests a dataset on a model according to `config` on the BastionLab Torch server.

        Args:
            config: Testing configuration that specifies the model, dataset and hyperparameters.
        """

        self.client.refresh_session_if_needed()

        return GRPCException.map_error(lambda: self.stub.Test(config))

    def delete_dataset(self, ref: Union["RemoteDataset", Reference]) -> None:
        """Deletes the dataset correponding to the given `ref` reference on the BastionLab Torch server.

        Args:
            ref: BastionLab Torch gRPC protocol reference of the dataset to be deleted.
        """
        from .remote_torch import RemoteDataset

        self.client.refresh_session_if_needed()

        if isinstance(ref, RemoteDataset):
            ref = Reference(
                identifier=ref.identifier, name="", description="", meta=bytes()
            )

        GRPCException.map_error(lambda: self.stub.DeleteDataset(ref))

    def delete_module(self, ref: Reference) -> None:
        """Deletes the module correponding to the given `ref` reference on the BastionLab Torch server.

        Args:
            ref: BastionLab Torch gRPC protocol reference of the module to be deleted.
        """

        self.client.refresh_session_if_needed()

        GRPCException.map_error(lambda: self.stub.DeleteModule(ref))

    def get_metric(self, run: Reference) -> Metric:
        """Returns the value of the metric associated with the given `run` reference.

        Args:
            run: BastionLab Torch gRPC protocol reference of the run whose metric is read.
        """

        self.client.refresh_session_if_needed()

        return GRPCException.map_error(lambda: self.stub.GetMetric(run))

    def RemoteDataset(self, *args, **kwargs) -> "RemoteDataset":
        """Returns a RemoteDataset object encapsulating a training and testing dataloaders
        on the remote server that uses this client to communicate with the server.

        Args:
            *args: all arguments are forwarded to the `RemoteDataset` constructor.
            **kwargs: all keyword arguments are forwarded to the `RemoteDataset` constructor.
        """
        from .remote_torch import RemoteDataset

        # Branch if inputs and labels are field with RemoteTensors
        # The branch triggers a gRPC call to actually convert `RemoteTensors` to `Dataset` and return
        # that Dataset (which will contain an identifier)
        inputs = kwargs.get("inputs")
        labels = kwargs.get("labels")

        if inputs and labels:
            return RemoteDataset._from_remote_tensors(self, inputs, labels)
        else:
            return RemoteDataset._from_dataset(self, *args, **kwargs)

    def RemoteLearner(self, *args, **kwargs) -> "RemoteLearner":
        """Returns a RemoteLearner object encapsulating a model and hyperparameters for
        training and testing on the remote server and that uses this client to communicate with the server.

        Args:
            *args: all arguments are forwarded to the `RemoteDataLoader` constructor.
            **kwargs: all keyword arguments are forwarded to the `RemoteDataLoader` constructor.
        """
        from .learner import RemoteLearner

        return RemoteLearner(self, *args, **kwargs)

    def RemoteTensor(self, tensor: torch.Tensor) -> "RemoteTensor":
        """Returns a RemoteTensor which represents a reference to the uploaded tensor.

        Args:
            tensor: The tensor to be uploaded.
        """
        from .remote_torch import RemoteTensor

        return RemoteTensor._send_tensor(self, tensor)
