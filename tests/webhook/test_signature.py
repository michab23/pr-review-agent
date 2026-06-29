import hashlib
import hmac

import pytest

from src.webhook.signature import verify_signature


def _make_sig(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


BODY = b'{"action":"opened"}'
SECRET = "test-secret"
VALID_SIG = _make_sig(BODY, SECRET)


@pytest.mark.parametrize("body,secret,header,expected", [
    (BODY, SECRET, VALID_SIG, True),
    (BODY, SECRET, "sha256=deadbeef", False),
    (BODY, SECRET, None, False),
    (BODY, SECRET, "", False),
    (BODY, SECRET, "sha256=", False),
    (b"tampered", SECRET, VALID_SIG, False),
    (BODY, "wrong-secret", VALID_SIG, False),
    (BODY, SECRET, "md5=abc123", False),
])
def test_verify_signature(body, secret, header, expected):
    assert verify_signature(body, secret, header) == expected


def test_constant_time_not_short_circuit():
    wrong = "sha256=" + "0" * 64
    assert verify_signature(BODY, SECRET, wrong) is False
