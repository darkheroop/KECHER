import hashlib
import hmac
import json
import time
import urllib.parse

from bot.webapp_api import validate_init_data

TOKEN = "123456:TESTTOKEN_ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def make_init_data(user: dict, *, token: str = TOKEN, auth_date: int | None = None) -> str:
    fields = {
        "user": json.dumps(user),
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "query_id": "AAF",
    }
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(fields)


def test_valid_init_data() -> None:
    user = {"id": 42, "first_name": "Owner"}
    assert validate_init_data(make_init_data(user), TOKEN) == user


def test_bad_hash_rejected() -> None:
    raw = make_init_data({"id": 1})
    assert validate_init_data(raw.replace("hash=", "hash=0"), TOKEN) is None


def test_wrong_token_rejected() -> None:
    raw = make_init_data({"id": 1}, token="999:OTHER")
    assert validate_init_data(raw, TOKEN) is None


def test_expired_init_data_rejected() -> None:
    raw = make_init_data({"id": 1}, auth_date=int(time.time()) - 200000)
    assert validate_init_data(raw, TOKEN) is None


def test_empty_inputs() -> None:
    assert validate_init_data("", TOKEN) is None
    assert validate_init_data("user=%7B%7D", "") is None
