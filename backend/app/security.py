"""HTTP headers that keep visitors' data from leaking out of the page.

- Content-Security-Policy: the app may only load scripts, styles and data
  from this server, so injected markup can't pull in or send anything.
- Referrer-Policy no-referrer: links and loads never carry the page
  address, which contains the private session ID, to another site.
- Cache-Control no-store on the API: analyses, reports and downloads are
  never kept by a CDN, a proxy, or the browser's disk cache.
- The rest stop framing (clickjacking), MIME sniffing, and access to
  devices the app never uses.
"""

import secrets

from starlette.types import Message

APP_CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        # React style attributes and Plotly's injected chart styles.
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob:",
        "font-src 'self' data:",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)

COMMON_HEADERS = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "x-frame-options": "DENY",
    "cross-origin-opener-policy": "same-origin",
    "permissions-policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    # Browsers ignore this over plain HTTP, so it's safe to send locally too.
    "strict-transport-security": "max-age=31536000; includeSubDomains",
}

# Swagger UI and ReDoc load their own scripts from a CDN; they get the common
# headers but not the app's script policy.
DOCS_PATHS = ("/docs", "/redoc")

# Public, unchanging files under /api that may be cached.
CACHEABLE_API_PATHS = ("/api/vendor/", "/api/sample.csv")


def report_csp(nonce: str) -> str:
    """For the printable report: its one inline script carries this nonce."""
    return "; ".join(
        [
            "default-src 'none'",
            f"script-src 'self' 'nonce-{nonce}'",
            "style-src 'unsafe-inline'",
            "img-src data: blob:",
            "font-src data:",
            "base-uri 'none'",
            "form-action 'none'",
            "frame-ancestors 'none'",
        ]
    )


def new_nonce() -> str:
    return secrets.token_urlsafe(16)


def add_security_headers(path: str, message: Message) -> None:
    """Add the headers to a response start message, keeping any the route set itself."""
    headers = message.setdefault("headers", [])
    present = {name.decode().lower() for name, _ in headers}

    wanted = dict(COMMON_HEADERS)
    if not path.startswith(DOCS_PATHS):
        wanted["content-security-policy"] = APP_CSP
    if path.startswith("/api/") and not path.startswith(CACHEABLE_API_PATHS):
        wanted["cache-control"] = "no-store"

    for name, value in wanted.items():
        if name not in present:
            headers.append((name.encode(), value.encode()))
