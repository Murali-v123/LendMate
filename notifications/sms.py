"""
Provider-independent SMS adapter  (extended from original).

New additions:
  - MSG91SMSBackend   real provider using MSG91 Flow API
  - validate_indian_mobile()  for phone number validation

The original MockSMSBackend, BaseSMSBackend and send_sms() helper are
preserved exactly so that existing test code and callers remain unchanged.
"""
import logging
import re
import uuid
from dataclasses import dataclass

import requests
from django.conf import settings
from django.utils.module_loading import import_string

logger = logging.getLogger(__name__)

# Maximum length of a single SMS segment (160 GSM-7, 70 Unicode).
# MSG91 handles multi-part automatically, but we log a warning for very long
# messages so template authors can keep them concise.
SMS_WARNING_LENGTH = 320


class SMSStatus:
    MOCKED = "mocked"
    SENT = "sent"
    FAILED = "failed"


@dataclass(frozen=True)
class SMSResult:
    status: str
    provider: str
    provider_message_id: str = ""
    error: str = ""

    @property
    def was_transmitted(self):
        return self.status == SMSStatus.SENT


class BaseSMSBackend:
    """Interface every SMS provider adapter must implement."""

    provider_name = "base"

    def send(self, to, message):
        raise NotImplementedError("SMS backends must implement send().")

    def get_delivery_status(self, provider_message_id):
        """Optional: check delivery status. Returns None if unsupported."""
        return None


class MockSMSBackend(BaseSMSBackend):
    """Development backend.  Logs the message and never contacts a network."""

    provider_name = "mock"

    def send(self, to, message):
        if len(message) > SMS_WARNING_LENGTH:
            logger.warning(
                "MOCK SMS: message to %s is %d characters (may incur extra cost on a real provider).",
                to, len(message),
            )
        message_id = f"mock-{uuid.uuid4().hex[:12]}"
        logger.info("MOCK SMS (not transmitted) to %s: %s", to, message)
        return SMSResult(
            status=SMSStatus.MOCKED,
            provider=self.provider_name,
            provider_message_id=message_id,
        )


class MSG91SMSBackend(BaseSMSBackend):
    """
    Real SMS backend using MSG91's Flow / OTP API (v5).

    Required environment variables (keep these server-side only):
        MSG91_AUTH_KEY      – your MSG91 authentication key
        MSG91_SENDER_ID     – DLT-approved 6-character sender ID (e.g. LNDMAT)
        MSG91_ROUTE         – transactional route number, usually "4"
        MSG91_COUNTRY       – country code without +, default "91" for India

    Important for Indian production SMS:
        1. Register on the DLT platform (Jio, Vodafone, Airtel, etc.).
        2. Get your entity ID and template ID approved.
        3. Use the DLT-approved message text exactly.
        4. Configure MSG91_SENDER_ID to your DLT-registered sender header.
    """

    provider_name = "msg91"
    API_URL = "https://api.msg91.com/api/v5/flow/"
    STATUS_URL = "https://api.msg91.com/api/logs.php"
    TIMEOUT = 15  # seconds

    def _auth_key(self):
        key = getattr(settings, "MSG91_AUTH_KEY", "") or ""
        if not key:
            raise ValueError(
                "MSG91_AUTH_KEY is not configured. Set it in your environment variables."
            )
        return key

    def _sender_id(self):
        return getattr(settings, "MSG91_SENDER_ID", "LNDMAT") or "LNDMAT"

    def _route(self):
        return getattr(settings, "MSG91_ROUTE", "4") or "4"

    def send(self, to, message):
        """
        Send an SMS via MSG91.

        For DLT-compliant production use, replace the plain-text `message`
        approach with a template_id + variable mapping as required by MSG91
        Flow API. This implementation uses the SMS API v2 endpoint which
        still supports plain text for pre-approved templates submitted in full.
        """
        auth_key = self._auth_key()

        # Normalise the number: strip spaces, dashes, parentheses.
        normalised = re.sub(r"[\s\-\(\)]", "", to)
        if not normalised.startswith("+"):
            # Assume India if no country code
            if not normalised.startswith("91") or len(normalised) == 10:
                normalised = "91" + normalised.lstrip("0")

        payload = {
            "sender": self._sender_id(),
            "route": self._route(),
            "country": "91",
            "sms": [
                {
                    "message": message,
                    "to": [normalised],
                }
            ],
        }

        try:
            response = requests.post(
                "https://api.msg91.com/api/sendhttp.php",
                # Use form-encoded for the v2 simple endpoint
                data={
                    "authkey": auth_key,
                    "mobiles": normalised,
                    "message": message,
                    "sender": self._sender_id(),
                    "route": self._route(),
                    "country": "91",
                    "response": "json",
                },
                timeout=self.TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()

            # MSG91 success: {"type":"success","message":"<id>"}
            if isinstance(data, dict) and data.get("type") == "success":
                provider_id = data.get("message", "") or ""
                logger.info(
                    "MSG91 SMS accepted for %s, provider_message_id=%s",
                    self._mask(to), provider_id,
                )
                return SMSResult(
                    status=SMSStatus.SENT,
                    provider=self.provider_name,
                    provider_message_id=provider_id,
                )

            # Partial / error response
            error_msg = str(data)[:300]
            logger.error("MSG91 returned non-success response for %s: %s", self._mask(to), error_msg)
            return SMSResult(
                status=SMSStatus.FAILED,
                provider=self.provider_name,
                error=error_msg,
            )

        except requests.Timeout:
            logger.error("MSG91 request timed out for %s", self._mask(to))
            return SMSResult(
                status=SMSStatus.FAILED,
                provider=self.provider_name,
                error="Provider request timed out.",
            )
        except requests.ConnectionError as exc:
            logger.error("MSG91 connection error for %s: %s", self._mask(to), str(exc)[:200])
            return SMSResult(
                status=SMSStatus.FAILED,
                provider=self.provider_name,
                error=f"Connection error: {str(exc)[:200]}",
            )
        except requests.HTTPError as exc:
            logger.error("MSG91 HTTP error for %s: %s", self._mask(to), str(exc)[:200])
            return SMSResult(
                status=SMSStatus.FAILED,
                provider=self.provider_name,
                error=f"HTTP error: {str(exc)[:200]}",
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected error sending MSG91 SMS to %s", self._mask(to))
            return SMSResult(
                status=SMSStatus.FAILED,
                provider=self.provider_name,
                error=str(exc)[:300],
            )

    def get_delivery_status(self, provider_message_id):
        """Query MSG91 delivery report for a sent message."""
        if not provider_message_id:
            return None
        try:
            auth_key = self._auth_key()
            response = requests.get(
                self.STATUS_URL,
                params={
                    "authkey": auth_key,
                    "requestId": provider_message_id,
                    "response": "json",
                },
                timeout=self.TIMEOUT,
            )
            response.raise_for_status()
            return response.json()
        except Exception:  # noqa: BLE001
            logger.exception("Failed to retrieve MSG91 delivery status for %s", provider_message_id)
            return None

    @staticmethod
    def _mask(number):
        """Mask mobile number for safe logging (never log full numbers)."""
        s = str(number)
        if len(s) > 4:
            return s[:2] + "*" * (len(s) - 4) + s[-2:]
        return "****"


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def validate_indian_mobile(number):
    """
    Returns True if `number` looks like a valid Indian mobile number.
    Accepts formats: +91XXXXXXXXXX, 91XXXXXXXXXX, 0XXXXXXXXXX, XXXXXXXXXX
    The 10-digit part must start with 6, 7, 8, or 9.
    """
    cleaned = re.sub(r"[\s\-\(\)\+]", "", str(number))
    # Strip leading country code
    if cleaned.startswith("0091"):
        cleaned = cleaned[4:]
    elif cleaned.startswith("91") and len(cleaned) == 12:
        cleaned = cleaned[2:]
    elif cleaned.startswith("0") and len(cleaned) == 11:
        cleaned = cleaned[1:]
    return bool(re.fullmatch(r"[6-9]\d{9}", cleaned))


def get_sms_backend():
    return import_string(settings.SMS_BACKEND)()


def send_sms(to, message):
    """
    Send one SMS through the configured backend.

    Errors are caught and returned as a FAILED result so that a notification
    problem never breaks the workflow that triggered it (for example, recording
    a payment).
    """
    backend = None
    try:
        backend = get_sms_backend()
        return backend.send(to, message)
    except Exception as exc:  # noqa: BLE001 - adapter errors must not crash callers
        logger.exception("SMS send failed for %s", to)
        return SMSResult(
            status=SMSStatus.FAILED,
            provider=getattr(backend, "provider_name", "unknown"),
            error=str(exc)[:500],
        )
