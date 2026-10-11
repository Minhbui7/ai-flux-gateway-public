import base64
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch

import pytest
from aiflux import tls
from aiflux.app import create_app
from aiflux.config import Settings
from aiflux.tls import public_http01_matches
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient


@pytest.mark.parametrize(
    ("status", "content", "matches"),
    [(200, "authorization", True), (200, "wrong", False), (403, "authorization", False)],
)
def test_http01_validator_identifies_itself_without_relaxing_checks(status, content, matches):
    with patch("aiflux.tls.requests.get", return_value=Mock(status_code=status, text=content)) as get:
        assert public_http01_matches("example.com", "token", "authorization") is matches
    get.assert_called_once_with(
        "http://example.com/.well-known/acme-challenge/token",
        headers={"User-Agent": "AIFLUX-TLS/1"},
        timeout=15, allow_redirects=False,
    )


def test_challenge_is_disabled_by_default(tmp_path):
    token = "a" * 43
    (tmp_path / token).write_text(token + "." + "b" * 43)
    client = TestClient(create_app(Settings(acme_challenge_directory=tmp_path)))
    assert client.get("/.well-known/acme-challenge/" + token).status_code == 404


def test_challenge_is_exact_public_value_only(tmp_path):
    token = "a" * 43
    value = token + "." + "b" * 43
    (tmp_path / token).write_text(value)
    client = TestClient(create_app(Settings(
        acme_challenge_enabled=True, acme_challenge_directory=tmp_path,
    )))
    response = client.get("/.well-known/acme-challenge/" + token)
    assert response.status_code == 200
    assert response.text == value
    assert response.headers["cache-control"] == "no-store"
    assert client.post("/.well-known/acme-challenge/" + token).status_code == 405
    assert client.get("/.well-known/acme-challenge/short").status_code == 404
    (tmp_path / token).write_text("not a key authorization")
    assert client.get("/.well-known/acme-challenge/" + token).status_code == 404
    (tmp_path / token).write_text("a" * 301)
    assert client.get("/.well-known/acme-challenge/" + token).status_code == 404
    (tmp_path / token).write_text("c" * 43 + "." + "b" * 43)
    assert client.get("/.well-known/acme-challenge/" + token).status_code == 404


def test_default_edge_backend_denies_all_methods():
    client = TestClient(create_app(Settings()))
    for method in ("get", "head", "post", "put", "delete", "patch", "options"):
        assert getattr(client, method)("/_edge-denied/api/me").status_code == 403


@pytest.mark.parametrize(
    ("environment", "expected_status"),
    [("staging", "validated"), ("production", "issued")],
)
def test_issuer_persists_only_the_approved_production_tls_secret(
    environment, expected_status, monkeypatch, tmp_path,
):
    hostname = "gateway.example.com"
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)]))
        .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)]))
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(minutes=1))
        .not_valid_after(datetime.now(UTC) + timedelta(days=30))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
        .sign(private_key, hashes.SHA256())
    )
    fullchain = certificate.public_bytes(serialization.Encoding.PEM).decode("ascii")
    finalized = Mock(fullchain_pem=fullchain)

    class FakeAcme:
        def __init__(self, *_):
            pass

        def new_account(self, *_):
            return None

        def new_order(self, *_):
            return Mock(authorizations=[])

        def poll_and_finalize(self, *_args, **_kwargs):
            assert _kwargs["deadline"].tzinfo is None
            return finalized

    vault = Mock()
    credential = Mock()
    monkeypatch.setattr(tls.rsa, "generate_private_key", lambda **_: private_key)
    monkeypatch.setattr(tls, "ManagedIdentityCredential", lambda **_: credential)
    monkeypatch.setattr(tls, "SecretClient", lambda **_: vault)
    monkeypatch.setenv("AZURE_CLIENT_ID", "00000000-0000-0000-0000-000000000001")
    monkeypatch.setattr(
        tls,
        "client",
        Mock(ClientNetwork=lambda *_args, **_kwargs: Mock(key=object()), ClientV2=FakeAcme),
    )
    monkeypatch.setattr(tls, "messages", Mock(
        Directory=Mock(from_json=lambda _: {}),
        NewRegistration=Mock(from_data=lambda **_: object()),
    ))

    args = Mock(
        environment=environment,
        hostname=hostname,
        email="ops@example.com",
        vault="https://example.vault.azure.net",
        challenge_directory=tmp_path / "challenges",
    )
    result = tls.issue(args)
    assert result["status"] == expected_status
    assert result["secret_name"] == (tls.CERTIFICATE_SECRET_NAME if environment == "production" else None)
    assert result["private_key_disk_written"] is False
    if environment == "production":
        vault.set_secret.assert_called_once()
        call = vault.set_secret.call_args
        assert call.args[0] == "aiflux-dev-tls"
        assert call.kwargs["content_type"] == "application/x-pkcs12"
        pfx = pkcs12.load_key_and_certificates(base64.b64decode(call.args[1]), None)
        assert pfx[0] is not None
        assert pfx[1].public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo,
        ) == private_key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    else:
        vault.set_secret.assert_not_called()
        credential.assert_not_called()
