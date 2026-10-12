"""Issue an HTTP-01 certificate from the private-integrated API container."""

import argparse
import base64
import json
import os
import re
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import josepy
import requests
from acme import challenges, client, messages
from azure.identity import ManagedIdentityCredential
from azure.keyvault.secrets import SecretClient
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

DIRECTORIES = {
    "staging": "https://acme-staging-v02.api.letsencrypt.org/directory",
    "production": "https://acme-v02.api.letsencrypt.org/directory",
}
CERTIFICATE_SECRET_NAME = "aiflux-dev-tls"


def public_http01_matches(hostname: str, token: str, validation: str) -> bool:
    response = requests.get(
        f"http://{hostname}/.well-known/acme-challenge/{token}",
        headers={"User-Agent": "AIFLUX-TLS/1"},
        timeout=15,
        allow_redirects=False,
    )
    return response.status_code == 200 and response.text == validation


def issue(args: argparse.Namespace) -> dict[str, Any]:
    credential = None
    vault = None
    if args.environment == "production":
        credential = ManagedIdentityCredential(client_id=os.environ["AZURE_CLIENT_ID"])
        vault = SecretClient(vault_url=args.vault, credential=credential)

    # Each issuance uses an ephemeral ACME account key. Persisting it would
    # require a second secret, outside the approved single-secret permission.
    account_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    network = client.ClientNetwork(josepy.JWKRSA(key=account_key), user_agent="AIFLUX-TLS/1")
    files: list[Path] = []
    try:
        directory = messages.Directory.from_json(network.get(DIRECTORIES[args.environment]).json())
        acme = client.ClientV2(directory, network)
        acme.new_account(messages.NewRegistration.from_data(email=args.email, terms_of_service_agreed=True))

        print("ACME phase: CA order eligibility", flush=True)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        csr = (
            x509.CertificateSigningRequestBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, args.hostname)]))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(args.hostname)]), critical=False)
            .sign(key, hashes.SHA256())
            .public_bytes(serialization.Encoding.PEM)
        )
        order = acme.new_order(csr)

        print("ACME phase: HTTP-01 public validation", flush=True)
        directory_path = Path(args.challenge_directory)
        directory_path.mkdir(mode=0o700, parents=True, exist_ok=True)
        for authorization in order.authorizations:
            if authorization.body.status == messages.STATUS_VALID:
                continue
            challenge = next(
                c for c in authorization.body.challenges if isinstance(c.chall, challenges.HTTP01)
            )
            response, validation = challenge.response_and_validation(network.key)
            token = challenge.chall.encode("token")
            if not re.fullmatch(r"[A-Za-z0-9_-]{20,128}", token):
                raise RuntimeError("Unexpected HTTP-01 token format")
            challenge_file = directory_path / token
            descriptor = os.open(challenge_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="ascii") as output:
                output.write(validation)
            files.append(challenge_file)

            deadline = time.monotonic() + 240
            while True:
                try:
                    if public_http01_matches(args.hostname, token, validation):
                        break
                except requests.RequestException:
                    pass
                if time.monotonic() >= deadline:
                    raise RuntimeError("Public HTTP-01 content did not match")
                time.sleep(10)
            acme.answer_challenge(challenge, response)

        finalized = acme.poll_and_finalize(order, deadline=datetime.now() + timedelta(minutes=5))
        certificates = x509.load_pem_x509_certificates(finalized.fullchain_pem.encode("ascii"))
        leaf, chain = certificates[0], certificates[1:]
        public_key = serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        if leaf.public_key().public_bytes(*public_key) != key.public_key().public_bytes(*public_key):
            raise RuntimeError("Issued certificate key mismatch")
        san = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        if san.get_values_for_type(x509.DNSName) != [args.hostname]:
            raise RuntimeError("Issued certificate SAN mismatch")

        secret_written = False
        if vault is not None:
            print("ACME phase: private-vault certificate upload", flush=True)
            pfx = pkcs12.serialize_key_and_certificates(
                args.hostname.encode("ascii"), key, leaf, chain, serialization.NoEncryption(),
            )
            vault.set_secret(
                CERTIFICATE_SECRET_NAME,
                base64.b64encode(pfx).decode("ascii"),
                content_type="application/x-pkcs12",
                expires_on=leaf.not_valid_after_utc,
                tags={"hostname": args.hostname, "ca": "letsencrypt", "environment": args.environment},
            )
            secret_written = True

        return {
            "status": "issued" if secret_written else "validated",
            "environment": args.environment,
            "hostname": args.hostname,
            "issuer": leaf.issuer.rfc4514_string(),
            "not_after": leaf.not_valid_after_utc.isoformat(),
            "thumbprint_sha256": leaf.fingerprint(hashes.SHA256()).hex(),
            "secret_name": CERTIFICATE_SECRET_NAME if secret_written else None,
            "private_key_disk_written": False,
            "http01_public_content_verified": True,
        }
    finally:
        for path in files:
            path.unlink(missing_ok=True)
        if vault is not None:
            vault.close()
        if credential is not None:
            credential.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment", choices=DIRECTORIES, required=True)
    parser.add_argument("--hostname", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--vault", required=True)
    parser.add_argument("--challenge-directory", default="/home/aiflux-acme-challenges")
    parser.add_argument("--marker", default="/home/aiflux-tls-status.json")
    parser.add_argument("--agree-terms", action="store_true", required=True)
    args = parser.parse_args()
    try:
        result = issue(args)
    except Exception as exc:
        result = {"status": "failed", "error_type": type(exc).__name__, "environment": args.environment}
        result["error_site"] = [
            {"module": Path(frame.filename).name, "line": frame.lineno, "function": frame.name}
            for frame in traceback.extract_tb(exc.__traceback__)[-4:]
        ]
        if isinstance(exc, messages.Error):
            result["ca_error_type"] = exc.typ
    Path(args.marker).write_text(json.dumps(result), encoding="utf-8")
    print(json.dumps(result), flush=True)
    if result["status"] not in ("validated", "issued"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
