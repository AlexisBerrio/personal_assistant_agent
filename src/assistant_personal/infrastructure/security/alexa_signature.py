from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from itertools import pairwise
from urllib.parse import urlparse

import httpx
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

# Requisitos de Alexa Skills Kit para endpoints HTTPS propios (no Lambda con trigger de Alexa):
# https://developer.amazon.com/en-US/docs/alexa/custom-skills/host-a-custom-skill-as-a-web-service.html
_EXPECTED_CERT_HOSTNAME = "s3.amazonaws.com"
_EXPECTED_CERT_PATH_PREFIX = "/echo.api/"
_EXPECTED_CERT_PORT = 443
_REQUIRED_LEAF_SAN = "echo-api.amazon.com"
_TIMESTAMP_TOLERANCE_SECONDS = 150

# Amazon reutiliza la misma URL de cadena de certificados durante meses — cachear evita
# descargarla en cada request. Sin expiración: el riesgo (servir una cadena revocada hasta el
# próximo reinicio del proceso) es aceptable frente al costo de reimplementar TTL/revocación
# para un proyecto educativo; producción real usaría OCSP/CRL.
_cert_chain_cache: dict[str, list[x509.Certificate]] = {}


class AlexaSignatureError(Exception):
    """La petición no pasa la verificación de firma de Alexa Skills Kit — origen no confiable."""


def _validate_cert_chain_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise AlexaSignatureError(f"SignatureCertChainUrl debe ser https, recibido: {parsed.scheme!r}")
    if (parsed.hostname or "").lower() != _EXPECTED_CERT_HOSTNAME:
        raise AlexaSignatureError(
            f"SignatureCertChainUrl debe apuntar a {_EXPECTED_CERT_HOSTNAME}, recibido: {parsed.hostname!r}"
        )
    if not parsed.path.startswith(_EXPECTED_CERT_PATH_PREFIX):
        raise AlexaSignatureError(
            f"SignatureCertChainUrl debe empezar con {_EXPECTED_CERT_PATH_PREFIX}, recibido: {parsed.path!r}"
        )
    if parsed.port is not None and parsed.port != _EXPECTED_CERT_PORT:
        raise AlexaSignatureError(
            f"SignatureCertChainUrl debe usar el puerto {_EXPECTED_CERT_PORT}, recibido: {parsed.port}"
        )


async def _fetch_cert_chain(url: str) -> list[x509.Certificate]:
    cached = _cert_chain_cache.get(url)
    if cached is not None:
        return cached
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(url)
        response.raise_for_status()
    certs = x509.load_pem_x509_certificates(response.content)
    if not certs:
        raise AlexaSignatureError("La cadena de certificados descargada está vacía")
    _cert_chain_cache[url] = certs
    return certs


def _verify_signed_by(cert: x509.Certificate, issuer_cert: x509.Certificate) -> None:
    issuer_key = issuer_cert.public_key()
    if not isinstance(issuer_key, rsa.RSAPublicKey):
        raise AlexaSignatureError("Certificado emisor con clave pública no soportada (se esperaba RSA)")
    try:
        issuer_key.verify(
            cert.signature,
            cert.tbs_certificate_bytes,
            padding.PKCS1v15(),
            cert.signature_hash_algorithm,  # type: ignore[arg-type]
        )
    except InvalidSignature as exc:
        raise AlexaSignatureError("Cadena de certificados inválida: un eslabón no verifica contra su emisor") from exc


def _validate_cert_chain(certs: list[x509.Certificate]) -> x509.Certificate:
    now = datetime.now(timezone.utc)
    for cert in certs:
        if not (cert.not_valid_before_utc <= now <= cert.not_valid_after_utc):
            raise AlexaSignatureError("Un certificado de la cadena está expirado o aún no es válido")
    for cert, issuer_cert in pairwise(certs):
        _verify_signed_by(cert, issuer_cert)

    leaf = certs[0]
    try:
        san = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    except x509.ExtensionNotFound as exc:
        raise AlexaSignatureError("El certificado líder no declara Subject Alternative Name") from exc
    if _REQUIRED_LEAF_SAN not in san.value.get_values_for_type(x509.DNSName):
        raise AlexaSignatureError(f"El certificado líder no incluye {_REQUIRED_LEAF_SAN} en su SAN")
    return leaf


def _verify_body_signature(leaf: x509.Certificate, signature_b64: str, raw_body: bytes) -> None:
    public_key = leaf.public_key()
    if not isinstance(public_key, rsa.RSAPublicKey):
        raise AlexaSignatureError("El certificado líder no usa una clave RSA")
    try:
        signature = base64.b64decode(signature_b64, validate=True)
    except (ValueError, TypeError) as exc:
        raise AlexaSignatureError("El header Signature no es base64 válido") from exc
    try:
        # SHA1withRSA es el algoritmo que Alexa Skills Kit exige para esta firma — no es una
        # elección propia, es parte fija del protocolo.
        public_key.verify(signature, raw_body, padding.PKCS1v15(), hashes.SHA1())
    except InvalidSignature as exc:
        raise AlexaSignatureError("La firma del body no coincide con el certificado líder") from exc


def _verify_timestamp(raw_body: bytes) -> None:
    try:
        body = json.loads(raw_body)
        timestamp_raw = body["request"]["timestamp"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise AlexaSignatureError("El body no trae request.timestamp") from exc
    try:
        request_time = datetime.fromisoformat(str(timestamp_raw).replace("Z", "+00:00"))
    except ValueError as exc:
        raise AlexaSignatureError(f"request.timestamp inválido: {timestamp_raw!r}") from exc
    delta_seconds = abs((datetime.now(timezone.utc) - request_time).total_seconds())
    if delta_seconds > _TIMESTAMP_TOLERANCE_SECONDS:
        raise AlexaSignatureError(
            f"request.timestamp fuera de tolerancia ({delta_seconds:.0f}s > "
            f"{_TIMESTAMP_TOLERANCE_SECONDS}s) — posible replay de una petición vieja"
        )


async def verify_alexa_request(*, raw_body: bytes, signature_b64: str | None, cert_chain_url: str | None) -> None:
    """Verifica que un request HTTP entrante viene genuinamente de los servidores de Alexa.

    Cuatro pasos exigidos por el protocolo de Alexa Skills Kit para un endpoint HTTPS propio
    (no aplica si se despliega como Lambda con trigger de Alexa, que ya lo garantiza la
    plataforma): la URL de la cadena de certificados debe apuntar al bucket S3 oficial de
    Amazon; la cadena debe ser válida (vigente, cada eslabón firmado por el siguiente) y el
    certificado líder debe declarar `echo-api.amazon.com`; la firma del body debe verificar
    contra la clave pública de ese certificado líder; y el timestamp de la petición debe estar
    dentro de la ventana de tolerancia, para descartar un replay de una petición capturada.
    """
    if not signature_b64 or not cert_chain_url:
        raise AlexaSignatureError("Faltan las cabeceras Signature/SignatureCertChainUrl")
    _validate_cert_chain_url(cert_chain_url)
    certs = await _fetch_cert_chain(cert_chain_url)
    leaf = _validate_cert_chain(certs)
    _verify_body_signature(leaf, signature_b64, raw_body)
    _verify_timestamp(raw_body)
