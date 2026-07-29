from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

import backend.db


KEY_FILE_NAME = ".secret_key"


def _key_path():
    return Path(backend.db.DB_PATH).parent / KEY_FILE_NAME


def _fernet():
    path = _key_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(Fernet.generate_key())
    return Fernet(path.read_bytes().strip())


def encrypt_secret(value):
    value = str(value or "")
    if not value:
        return ""
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value):
    if not value:
        return ""
    try:
        return _fernet().decrypt(str(value).encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise RuntimeError(
            "本地密钥无法解密公众号 AppSecret，请重新填写"
        ) from exc
