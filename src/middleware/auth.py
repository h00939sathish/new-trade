import hmac
import logging
from typing import Optional

logger = logging.getLogger("middleware.auth")


def verify_bearer_token(
    auth_header_value: Optional[str],
    expected_token: str,
) -> bool:
    if not auth_header_value:
        return False
    expected = f"Bearer {expected_token}"
    return hmac.compare_digest(auth_header_value.strip(), expected)


async def require_auth(
    reader,
    writer,
    request_text: str,
    expected_token: str,
) -> bool:
    if not expected_token:
        return True
    auth_header: Optional[str] = None
    for line in request_text.split("\r\n"):
        if line.lower().startswith("authorization:"):
            auth_header = line.split(":", 1)[1].strip()
            break
    if not verify_bearer_token(auth_header, expected_token):
        body = b"Unauthorized"
        response = (
            "HTTP/1.1 401 Unauthorized\r\n"
            "Content-Type: text/plain\r\n"
            f"Content-Length: {len(body)}\r\n"
            "\r\n"
        ).encode() + body
        writer.write(response)
        await writer.drain()
        writer.close()
        return False
    return True
