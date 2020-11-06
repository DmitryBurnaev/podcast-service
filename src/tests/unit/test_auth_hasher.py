import uuid

from modules.auth.hasher import PBKDF2PasswordHasher


def test_password_encode():
    hasher = PBKDF2PasswordHasher()
    row_password = uuid.uuid4().hex
    encoded = hasher.encode(row_password, salt="test_salt")
    algorithm, iterations, salt, hash_ = encoded.split("$", 3)
    assert salt == "test_salt"
    assert algorithm == "pbkdf2_sha256"
    assert hash_ != row_password


def test_password_verify():
    hasher = PBKDF2PasswordHasher()
    row_password = uuid.uuid4().hex
    encoded = hasher.encode(row_password, salt="test_salt")
    assert hasher.verify(row_password, encoded)
