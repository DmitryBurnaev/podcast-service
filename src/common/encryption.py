import base64
import logging
from typing import NamedTuple

from Crypto.Cipher import AES

from common.exceptions import ImproperlyConfiguredError
from core import settings

logger = logging.getLogger(__name__)


class EncodingError(Exception):
    pass


class StructMessage(NamedTuple):
    nonce: bytes
    encoded_message: bytes
    tag: bytes


class SensitiveData:
    """Encrypts/decrypt incoming data (using AES256 encryption)"""

    AES256_PREFIX = "AES256"
    AES_KEY_LENGTH = int(256 / 8)

    def __init__(self) -> None:
        if not (encrypt_key := settings.SENS_DATA_ENCRYPT_KEY):
            raise ImproperlyConfiguredError(
                "Missed encrypt key for encryption sensitive data (env 'SENS_DATA_ENCRYPT_KEY')"
            )

        self.encrypt_key = self._cast_encrypt_key(encrypt_key)

    def encrypt(self, data: str) -> str:
        """Allows to encrypt giving data with provided settings.SENS_DATA_ENCRYPT_KEY"""
        try:
            cipher = AES.new(self.encrypt_key, AES.MODE_EAX)
            encoded_message, tag = cipher.encrypt_and_digest(data.encode())
        except ValueError as exc:
            logger.exception("Couldn't encode data: %r", exc)
            raise EncodingError("Couldn't encode data") from exc

        nonce_b64b = base64.b64encode(cipher.nonce).decode()
        encoded_message_b64b = base64.b64encode(encoded_message).decode()
        tag_b64b = base64.b64encode(tag).decode()
        return f"{self.AES256_PREFIX};{nonce_b64b};{encoded_message_b64b};{tag_b64b}"

    def decrypt(self, data: str) -> str:
        """Allows to decrypt data with provided settings.SENS_DATA_ENCRYPT_KEY"""
        struct_message = self._get_struct_message(data)
        try:
            cipher = AES.new(self.encrypt_key, AES.MODE_EAX, nonce=struct_message.nonce)
            decrypted_message = cipher.decrypt(struct_message.encoded_message).decode()
            cipher.verify(struct_message.tag)
        except ValueError as exc:
            logger.exception("Couldn't decode data: %r", exc)
            raise EncodingError("Couldn't decode data") from exc

        return decrypted_message

    def _get_struct_message(self, encoded_data: str) -> StructMessage:
        parts = encoded_data.split(";")
        if len(parts) != 4:
            logger.warning("Couldn't encode message: %s (bad format)", encoded_data)
            raise ValueError(
                f"Couldn't encode message: not enough parts: expected: 4 actual: {len(parts)}"
            )

        prefix, nonce_b64b, encoded_message_b64b, tag_b64b = parts
        if prefix != self.AES256_PREFIX:
            raise ValueError(f"Couldn't encode message: unexpected prefix detected: {prefix}")

        return StructMessage(
            nonce=base64.b64decode(nonce_b64b.encode()),
            encoded_message=base64.b64decode(encoded_message_b64b.encode()),
            tag=base64.b64decode(tag_b64b.encode()),
        )

    @classmethod
    def _cast_encrypt_key(cls, value: str) -> bytes:
        """Simple tool for checking encrypt key by length (can cut if too long)"""
        length = cls.AES_KEY_LENGTH
        if len(value) < length:
            raise ValueError(f"Not enough length encryption key: {length}, actual: {len(value)}")

        return value[:length].encode()
