import base64
from typing import NamedTuple
from unittest.mock import patch, Mock

import pytest

from common.encryption import SensitiveData


class MockedCipherAES:
    def __init__(self):
        self.encrypt_and_digest = Mock()
        self.nonce = b"TEST_NONCE"


class MockAESResult(NamedTuple):
    cipher: MockedCipherAES
    new_mock: Mock


@pytest.fixture
def mocked_aes(monkeypatch) -> MockAESResult:
    mocked_aes_object = MockedCipherAES()

    with patch("Cryptodome.Cipher.AES.new") as mock_new:
        mock_new.return_value = mock_new
        yield MockAESResult(cipher=mocked_aes_object, new_mock=mock_new)


class TestEncryptSensitiveData:
    encrypt_key = "testEncryptKey"
    sens_data = "sens_data"

    def test_encrypt(self, mocked_aes):
        mocked_aes.cipher.encrypt_and_digest.return_value = (b"test_encoded_message", b"test_tag")
        encrypted = SensitiveData(self.encrypt_key).encrypt(self.sens_data)

        expected_nonce_b64b = base64.b64encode(b"TEST_NONCE").decode()
        expected_encoded_message_b64b = base64.b64encode(b"test_encoded_message").decode()
        expected_tag_b64b = base64.b64encode(b"test_tag").decode()
        assert encrypted == (
            f"AES256;{expected_nonce_b64b};{expected_encoded_message_b64b};{expected_tag_b64b}"
        )

        mocked_aes.cipher.encrypt_and_digest.assert_called_with(self.sens_data.encode())
        mocked_aes.new_mock.assert_called_with(self.encrypt_key)

    def test_decrypt(self):
        assert False
