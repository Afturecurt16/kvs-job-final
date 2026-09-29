"""Install the official Russian Trusted CA chain for MAX API requests.

The certificate URLs are published in RuStore's server setup instructions.
Run during the Docker build so no certificate download occurs at runtime.
"""

from pathlib import Path
from ssl import PEM_cert_to_DER_cert
from urllib.request import urlopen


CERTIFICATE_URLS = (
    "https://gu-st.ru/content/lending/russian_trusted_root_ca_pem.crt",
    "https://gu-st.ru/content/lending/russian_trusted_sub_ca_pem.crt",
)
OUTPUT = Path("/app/certs/russian_trusted_ca.pem")
MAX_CERTIFICATE_SIZE = 64 * 1024


def download_certificate(url: str) -> str:
    with urlopen(url, timeout=20) as response:
        data = response.read(MAX_CERTIFICATE_SIZE + 1)
    if len(data) > MAX_CERTIFICATE_SIZE:
        raise ValueError(f"Certificate is unexpectedly large: {url}")
    certificate = data.decode("ascii").strip()
    if not certificate.startswith("-----BEGIN CERTIFICATE-----"):
        raise ValueError(f"Not a PEM certificate: {url}")
    PEM_cert_to_DER_cert(certificate)
    return certificate


if __name__ == "__main__":
    certificates = [download_certificate(url) for url in CERTIFICATE_URLS]
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(certificates) + "\n", encoding="ascii")
