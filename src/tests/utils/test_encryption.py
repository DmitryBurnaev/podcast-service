from unittest.mock import patch, Mock

import pytest

from common.encryption import SensitiveData


class MockedCipherAES:
    def __init__(self):
        self.encrypt_and_digest = Mock()


@pytest.fixture
def mocked_aes(monkeypatch):
    mocked_aes_object = MockedCipherAES()

    with patch("Cryptodome.Cipher.AES.new") as mock_new:
        mock_new.return_value = mock_new
        yield mocked_aes_object


class TestEncryptSensitiveData:
    encrypt_key = "testEncryptKey"
    sens_data = "sens_data"

    @patch("Cryptodome.Cipher.AES.new")
    # @patch("Cryptodome.Cipher._mode_eax.EaxMode.encrypt_and_digest")
    def test_encrypt(self, mocked_aes_new):
        mocked_aes_new.return_value = MockedCipherAES()
        encrypted = SensitiveData(self.encrypt_key).encrypt(self.sens_data)
        assert encrypted == ""
        assert False

    def test_decrypt(self):
        assert False
