import unittest

from datetime import timedelta

from app import ClientProfile, OneTimeSecretDatabase
from flask import Flask, current_app


class TestClientProfile(unittest.TestCase):
    DATA_ROOT = "/my/data/root"
    CERT_FINGERPRINT = '4d5f61bcd81f5dc224cb0b34764d1b2ef65309d1'

    @classmethod
    def setUpClass(cls):
        cls.flask_app = Flask('test')
        cls.flask_app.config.update({'DATA_ROOT': cls.DATA_ROOT})

    def test_files_prefix(self):
        client = ClientProfile(
            mac_address='52:54:00:12:34:56',
            ip_address="10.0.0.1",
            client_cert_serial_number='03',
            client_cert_fingerprint=self.CERT_FINGERPRINT)

        with self.flask_app.app_context():
            assert client.files_prefix == f"{self.DATA_ROOT}/{self.CERT_FINGERPRINT}"


class TestOneTimeSecretDatabase(unittest.TestCase):
    SECRET = "secret"

    def test_normal_use_case(self):
        db = OneTimeSecretDatabase()
        assert len(db.db) == 0

        token = db.set(secret=self.SECRET, validity_period=timedelta(hours=1))
        assert len(db.db) == 1

        assert db.get(None) is None
        assert len(db.db) == 1

        assert db.get(token) == self.SECRET
        assert len(db.db) == 0

    def test_accessing_secret_twice(self):
        db = OneTimeSecretDatabase()
        token = db.set(secret=self.SECRET, validity_period=timedelta(hours=1))
        assert db.get(token) == self.SECRET
        assert db.get(token) is None


# TODO: Add more tests

if __name__ == '__main__':
    unittest.main()
