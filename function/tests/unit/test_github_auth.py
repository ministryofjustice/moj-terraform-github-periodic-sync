"""Test the App JWT builder. Guarded: only runs when jwt + cryptography present
(the 'live' extra); skipped in the dependency-free unit run.
"""

import pytest


def test_app_jwt_has_issuer_and_verifies():
    pytest.importorskip("jwt")
    pytest.importorskip("cryptography")

    import jwt as pyjwt
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    from scim_sync.adapters.github_auth import _app_jwt

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()

    token = _app_jwt("12345", pem)
    decoded = pyjwt.decode(
        token, key.public_key(), algorithms=["RS256"], options={"verify_exp": False}
    )
    assert decoded["iss"] == "12345"
    assert decoded["exp"] > decoded["iat"]
