import base64
import uuid
from typing import NamedTuple
from unittest.mock import patch, Mock

import pytest
from Cryptodome.Cipher import AES

from common.encryption import SensitiveData

ENCRYPT_KEY = (f"test_encr_key_{uuid.uuid4().hex}"[: int(256 / 8)]).encode()
SENS_DATA = "sens_data"
ENCRYPTED_SENS_DATA = b"encrypted_sens_data"
ENCRYPT_TAG = b"encrypt_tag"
ENCRYPT_NONCE = b"TEST_NONCE"


class MockedCipherAES:
    def __init__(self):
        self.encrypt_and_digest = Mock()
        self.decrypt = Mock()
        self.verify = Mock()
        self.nonce = ENCRYPT_NONCE


class MockAESResult(NamedTuple):
    cipher: MockedCipherAES
    mock_new: Mock


@pytest.fixture
def mocked_aes(monkeypatch) -> MockAESResult:
    mocked_aes_object = MockedCipherAES()

    with patch("Cryptodome.Cipher.AES.new") as mock_new:
        mock_new.return_value = mocked_aes_object
        yield MockAESResult(cipher=mocked_aes_object, mock_new=mock_new)


@patch("core.settings.SENS_DATA_ENCRYPT_KEY", ENCRYPT_KEY.decode())
class TestEncryptSensitiveData:
    @staticmethod
    def _encrypted_string() -> str:
        expected_nonce_b64b = base64.b64encode(ENCRYPT_NONCE).decode()
        expected_encoded_message_b64b = base64.b64encode(ENCRYPTED_SENS_DATA).decode()
        expected_tag_b64b = base64.b64encode(ENCRYPT_TAG).decode()
        return f"AES256;{expected_nonce_b64b};{expected_encoded_message_b64b};{expected_tag_b64b}"

    def test_encrypt(self, mocked_aes: MockAESResult):
        mocked_aes.cipher.encrypt_and_digest.return_value = (ENCRYPTED_SENS_DATA, ENCRYPT_TAG)

        encrypted = SensitiveData().encrypt(SENS_DATA)
        assert encrypted == self._encrypted_string()

        mocked_aes.mock_new.assert_called_with(ENCRYPT_KEY, AES.MODE_EAX)
        mocked_aes.cipher.encrypt_and_digest.assert_called_with(SENS_DATA.encode())

    def test_decrypt(self, mocked_aes: MockAESResult):
        mocked_aes.cipher.decrypt.return_value = SENS_DATA.encode()

        encrypted_data = self._encrypted_string()
        decrypted = SensitiveData().decrypt(encrypted_data)
        assert decrypted == SENS_DATA

        mocked_aes.mock_new.assert_called_with(ENCRYPT_KEY, AES.MODE_EAX, nonce=ENCRYPT_NONCE)
        mocked_aes.cipher.decrypt.assert_called_with(ENCRYPTED_SENS_DATA)
        mocked_aes.cipher.verify.assert_called_with(ENCRYPT_TAG)

    def test_encrypt_decrypt__no_mock(self):
        encrypted = SensitiveData().encrypt(SENS_DATA)
        assert SENS_DATA not in encrypted
        assert "AES256;" in encrypted
        assert len(encrypted.split(";")) == 4

        decrypted = SensitiveData().decrypt(encrypted)
        assert decrypted == SENS_DATA
