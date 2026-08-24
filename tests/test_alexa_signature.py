from __future__ import annotations

import base64
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID

from src.assistant_personal.infrastructure.security import alexa_signature as sig
from src.assistant_personal.infrastructure.security.alexa_signature import (
    AlexaSignatureError,
    verify_alexa_request,
)

_VALID_CERT_URL = "https://s3.amazonaws.com/echo.api/echo-api-cert.pem"


def _build_cert_chain(
    *, leaf_san: str | None = "echo-api.amazon.com", expired: bool = False
) -> tuple[list[x509.Certificate], rsa.RSAPrivateKey]:
    """Cadena raíz autofirmada + hoja firmada por la raíz, imitando la forma real que Amazon
    publica (aunque autofirmada, no encadenada a una CA pública) — suficiente para probar la
    lógica de validación de la cadena sin depender de red ni de certificados reales."""
    root_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)
    not_before = now - timedelta(days=1)
    not_after = (now - timedelta(days=1)) if expired else (now + timedelta(days=365))

    root_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test Root CA")])
    root_cert = (
        x509.CertificateBuilder()
        .subject_name(root_name)
        .issuer_name(root_name)
        .public_key(root_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .sign(root_key, hashes.SHA256())
    )

    leaf_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "echo-api")])
    leaf_builder = (
        x509.CertificateBuilder()
        .subject_name(leaf_name)
        .issuer_name(root_name)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_after)
    )
    if leaf_san is not None:
        leaf_builder = leaf_builder.add_extension(x509.SubjectAlternativeName([x509.DNSName(leaf_san)]), critical=False)
    leaf_cert = leaf_builder.sign(root_key, hashes.SHA256())

    return [leaf_cert, root_cert], leaf_key


def _sign_body(leaf_key: rsa.RSAPrivateKey, raw_body: bytes) -> str:
    signature = leaf_key.sign(raw_body, padding.PKCS1v15(), hashes.SHA1())
    return base64.b64encode(signature).decode()


def _alexa_body(timestamp: datetime | None = None) -> bytes:
    ts = (timestamp or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return json.dumps(
        {
            "session": {"sessionId": "amzn1.echo-api.session.abc"},
            "request": {"type": "LaunchRequest", "timestamp": ts},
        }
    ).encode()


class ValidateCertChainUrlTests(unittest.TestCase):
    def test_accepts_the_official_amazon_url_shape(self) -> None:
        sig._validate_cert_chain_url(_VALID_CERT_URL)  # no debe lanzar

    def test_rejects_non_https_scheme(self) -> None:
        with self.assertRaises(AlexaSignatureError):
            sig._validate_cert_chain_url("http://s3.amazonaws.com/echo.api/cert.pem")

    def test_rejects_wrong_hostname(self) -> None:
        with self.assertRaises(AlexaSignatureError):
            sig._validate_cert_chain_url("https://evil.example.com/echo.api/cert.pem")

    def test_rejects_wrong_path_prefix(self) -> None:
        with self.assertRaises(AlexaSignatureError):
            sig._validate_cert_chain_url("https://s3.amazonaws.com/not-echo-api/cert.pem")

    def test_rejects_non_standard_port(self) -> None:
        with self.assertRaises(AlexaSignatureError):
            sig._validate_cert_chain_url("https://s3.amazonaws.com:8443/echo.api/cert.pem")


class ValidateCertChainTests(unittest.TestCase):
    def test_accepts_a_valid_chain_and_returns_the_leaf(self) -> None:
        certs, _ = _build_cert_chain()

        leaf = sig._validate_cert_chain(certs)

        self.assertEqual(leaf, certs[0])

    def test_rejects_an_expired_chain(self) -> None:
        certs, _ = _build_cert_chain(expired=True)

        with self.assertRaises(AlexaSignatureError):
            sig._validate_cert_chain(certs)

    def test_rejects_a_leaf_without_the_required_san(self) -> None:
        certs, _ = _build_cert_chain(leaf_san="not-echo-api.amazon.com")

        with self.assertRaises(AlexaSignatureError):
            sig._validate_cert_chain(certs)

    def test_rejects_a_leaf_with_no_san_extension_at_all(self) -> None:
        certs, _ = _build_cert_chain(leaf_san=None)

        with self.assertRaises(AlexaSignatureError):
            sig._validate_cert_chain(certs)


class VerifyBodySignatureTests(unittest.TestCase):
    def test_accepts_a_signature_produced_by_the_leaf_key(self) -> None:
        certs, leaf_key = _build_cert_chain()
        body = _alexa_body()
        signature_b64 = _sign_body(leaf_key, body)

        sig._verify_body_signature(certs[0], signature_b64, body)  # no debe lanzar

    def test_rejects_a_signature_over_a_different_body(self) -> None:
        certs, leaf_key = _build_cert_chain()
        signature_b64 = _sign_body(leaf_key, _alexa_body())

        with self.assertRaises(AlexaSignatureError):
            sig._verify_body_signature(certs[0], signature_b64, b'{"tampered": true}')

    def test_rejects_a_signature_produced_by_a_different_key(self) -> None:
        certs, _ = _build_cert_chain()
        _, other_key = _build_cert_chain()
        body = _alexa_body()
        signature_b64 = _sign_body(other_key, body)

        with self.assertRaises(AlexaSignatureError):
            sig._verify_body_signature(certs[0], signature_b64, body)

    def test_rejects_non_base64_signature(self) -> None:
        certs, _ = _build_cert_chain()

        with self.assertRaises(AlexaSignatureError):
            sig._verify_body_signature(certs[0], "not-valid-base64!!", _alexa_body())


class VerifyTimestampTests(unittest.TestCase):
    def test_accepts_a_fresh_timestamp(self) -> None:
        sig._verify_timestamp(_alexa_body())  # no debe lanzar

    def test_rejects_a_stale_timestamp(self) -> None:
        stale = datetime.now(timezone.utc) - timedelta(seconds=300)

        with self.assertRaises(AlexaSignatureError):
            sig._verify_timestamp(_alexa_body(stale))

    def test_rejects_a_body_without_timestamp(self) -> None:
        with self.assertRaises(AlexaSignatureError):
            sig._verify_timestamp(b'{"request": {}}')


class VerifyAlexaRequestIntegrationTests(unittest.IsolatedAsyncioTestCase):
    """Ejercita `verify_alexa_request` de punta a punta, mockeando solo la descarga por red de
    la cadena de certificados (`_fetch_cert_chain`) — el resto de la lógica (URL, cadena,
    firma, timestamp) corre real contra una cadena sintética."""

    async def asyncSetUp(self) -> None:
        sig._cert_chain_cache.clear()

    async def test_accepts_a_correctly_signed_request(self) -> None:
        certs, leaf_key = _build_cert_chain()
        body = _alexa_body()
        signature_b64 = _sign_body(leaf_key, body)

        with patch.object(sig, "_fetch_cert_chain", new=AsyncMock(return_value=certs)):
            await verify_alexa_request(raw_body=body, signature_b64=signature_b64, cert_chain_url=_VALID_CERT_URL)

    async def test_rejects_missing_headers(self) -> None:
        with self.assertRaises(AlexaSignatureError):
            await verify_alexa_request(raw_body=_alexa_body(), signature_b64=None, cert_chain_url=None)

    async def test_rejects_a_forged_cert_chain_url(self) -> None:
        _, leaf_key = _build_cert_chain()
        body = _alexa_body()
        signature_b64 = _sign_body(leaf_key, body)

        with self.assertRaises(AlexaSignatureError):
            await verify_alexa_request(
                raw_body=body,
                signature_b64=signature_b64,
                cert_chain_url="https://evil.example.com/echo.api/cert.pem",
            )


if __name__ == "__main__":
    unittest.main()
