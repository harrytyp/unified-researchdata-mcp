"""Unit test for session_email: pulling the requester's address off a token.

The real cookie is a Keycloak access token, which cannot be minted here (NOMAD
treats any JWT with more than {user, exp} as a Keycloak token and then wants a
verifiable kid). So the decode is tested against the payload shapes it has to
cope with - a Keycloak token with and without an email claim, a NOMAD simple
token, a PAT and rubbish. No network, no NOMAD.
"""
import base64
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from session_email import decode_claims, email_from_token  # noqa: E402

FAILS = []


def check(label, cond, detail=''):
    if not cond:
        FAILS.append(label)
    print(f'  [{"OK  " if cond else "FAIL"}] {label}{" - " + str(detail) if detail else ""}')


def jwt(payload: dict, header: dict | None = None) -> str:
    """A JWT whose payload is exactly what we want to feed in - signature
    unverified, which is all the prefill needs."""
    def part(obj):
        return base64.urlsafe_b64encode(
            json.dumps(obj).encode()).decode().rstrip('=')
    return f'{part(header or {"alg": "RS256", "kid": "abc"})}.{part(payload)}.sig'


print('=== Keycloak-Token (der echte Fall) ===')
kc = jwt({'sub': '41875c3d-785d-4c2f-a7f5-1c81e6290276',
          'preferred_username': 'kolja.knodel',
          'email': 'kolja.knodel@tum.de', 'email_verified': True})
check('E-Mail aus dem Keycloak-Token', email_from_token(kc) == 'kolja.knodel@tum.de',
      email_from_token(kc))
check('weitere Claims bleiben lesbar',
      decode_claims(kc).get('preferred_username') == 'kolja.knodel')

print()
print('=== Keycloak-Token ohne E-Mail-Claim ===')
check('leer, kein Absturz',
      email_from_token(jwt({'sub': 'x', 'preferred_username': 'y'})) == '')

print()
print('=== NOMAD-Token ohne E-Mail (simple token, PAT, upload token) ===')
simple = jwt({'user': '41875c3d', 'exp': 99})
check('simple token liefert keine E-Mail', email_from_token(simple) == '')
check('Claims trotzdem lesbar', decode_claims(simple).get('user') == '41875c3d')
check('PAT liefert keine E-Mail',
      email_from_token('pat_abcdefghijklmnopqrstuvwxyz0123456789') == '')
check('upload token liefert keine E-Mail', email_from_token('upload_token_abc') == '')

print()
print('=== Unbrauchbares ===')
for bad in ('', 'nonsense', 'a.b', 'a.b.c.d', 'Bearer not-a-jwt',
            jwt({'email': ''}), jwt({'email': None})):
    check(f'kein Absturz bei {bad[:26]!r}', email_from_token(bad) == '',
          repr(email_from_token(bad)))
check('Whitespace wird getrimmt', email_from_token(jwt({'email': '  a@b.de  '})) == 'a@b.de')
check('None wirft nicht', decode_claims(None) == {})  # type: ignore[arg-type]

print()
print('ERGEBNIS:', 'ALLE CHECKS BESTANDEN' if not FAILS
      else f'{len(FAILS)} FEHLER: ' + '; '.join(FAILS))
sys.exit(1 if FAILS else 0)
