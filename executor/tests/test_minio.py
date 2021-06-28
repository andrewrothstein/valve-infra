from unittest.mock import patch
import os

from minioclient import MinioClient


@patch("minioclient.Minio", autospec=True)
def test_client_instanciation__defaults(minio_mock):
    MinioClient()

    minio_mock.assert_called_once_with(endpoint="10.42.0.1:9000", access_key="minioadmin",
                                       secret_key="random", secure=False)


@patch("minioclient.Minio", autospec=True)
def test_client_instanciation__custom_params(minio_mock):
    with patch.dict(os.environ, {"MINIO_URL": "http://hello-world",
                                 "MINIO_ROOT_PASSWORD": "123456789"}):
        MinioClient()

    minio_mock.assert_called_once_with(endpoint="hello-world", access_key="minioadmin",
                                       secret_key="123456789", secure=False)


def test_is_local_url():
    minio = MinioClient()

    assert minio.is_local_url("http://10.42.0.1:9000/toto")
    assert not minio.is_local_url("http://hello-world/toto")

    with patch.dict(os.environ, {"MINIO_URL": "http://hello-world"}):
        minio = MinioClient()

        assert not minio.is_local_url("http://10.42.0.1:9000/toto")
        assert minio.is_local_url("http://hello-world/toto")


class MockStream:
    def iter_content(self, _):
        yield b'hello world'

    def raise_for_status(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


@patch("minioclient.requests.get", return_value=MockStream())
@patch("minioclient.Minio", autospec=True)
@patch("minioclient.tempfile.NamedTemporaryFile", autospec=True)
def test_save_boot_artifact(named_temp_mock, minio_mock, get_mock):
    client = MinioClient()

    named_temp_mock().__enter__().name = "/tmp/temp_file"
    client.save_boot_artifact("https://toto.com/path", "/toto/path")

    client._client.fput_object.assert_called_once_with("boot", "/toto/path", "/tmp/temp_file")
