"""Transactional email over HTTPS; no SMTP ports or additional SDK required."""
import json
import logging
import os
import re
import urllib.error
import urllib.request


def normalize_email(value):
    value = (value or '').strip().lower()
    if len(value) > 254 or not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+", value):
        return ''
    local = value.split('@')[0]
    return value if len(local) <= 64 and not local.startswith('.') and not local.endswith('.') and '..' not in local else ''


def email_ready():
    return bool(os.environ.get('RESEND_API_KEY', '').strip() and normalize_email(os.environ.get('EMAIL_FROM', '')))


def send_email(recipient, subject, body):
    if not email_ready() or not normalize_email(recipient):
        return False
    payload = json.dumps({'from': os.environ['EMAIL_FROM'].strip(), 'to': [recipient],
                          'subject': subject, 'text': body}).encode()
    req = urllib.request.Request('https://api.resend.com/emails', data=payload, method='POST',
        headers={'Authorization': 'Bearer ' + os.environ['RESEND_API_KEY'].strip(),
                 'Content-Type': 'application/json', 'User-Agent': 'TrustMap/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read())
            return 200 <= response.status < 300 and bool(result.get('id'))
    except Exception as exc:
        # Never log payloads, recipients, codes, headers, or provider response bodies.
        logging.getLogger(__name__).warning('Email delivery failed (%s, status=%s)', type(exc).__name__, getattr(exc, 'code', 'unknown'))
        return False
