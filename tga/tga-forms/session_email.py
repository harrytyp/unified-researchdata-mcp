"""Read the requester's email address out of the NOMAD login token.

Kept in its own module so it can be tested without importing the NiceGUI app
(app.py calls ui.run at import time).

NOMAD resolves the logged-in user the same way this does: nomad.auth.keycloak
builds the user from the access token payload (payload['email']). So if the
token carries an address, NOMAD already has it - and the form can show it.

The decode is unverified on purpose. It only prefills an editable field; the
NOMAD API validates the token for real when the request is submitted, so a
forged payload buys nothing.
"""
import base64
import json


def decode_claims(token: str) -> dict:
    """Return the JWT payload of a token, or {} if it is not a decodable JWT.

    Simple tokens, PATs and upload tokens carry {user, exp} only, so this
    returns {} for them - exactly what we want, since they hold no address.
    """
    if not token or not isinstance(token, str):
        return {}
    parts = token.strip().removeprefix('Bearer ').strip().split('.')
    if len(parts) != 3:
        return {}
    payload = parts[1]
    payload += '=' * (-len(payload) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return {}
    return claims if isinstance(claims, dict) else {}


def email_from_token(token: str) -> str:
    """The email claim of a login token, or '' when there is none."""
    value = decode_claims(token).get('email')
    return str(value).strip() if value else ''
