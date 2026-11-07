"""
Official Meta WhatsApp Business Platform (Cloud API) adapter and provider abstraction.

Provides:
  - BaseWhatsAppBackend (abstract interface)
  - MockWhatsAppBackend (simulated, no real transmission, returns MOCKED)
  - MetaWhatsAppCloudBackend (official Cloud API, returns SUBMITTED with provider ID)
  - send_whatsapp_template() (safe caller that catches exceptions)
  - normalize_phone_number() (cleans and validates Indian phone numbers for Meta)
"""
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import requests
from django.conf import settings
from django.utils.module_loading import import_string

logger = logging.getLogger(__name__)


class WhatsAppStatus:
    MOCKED = "mocked"
    SUBMITTED = "submitted"
    FAILED = "failed"


@dataclass(frozen=True)
class WhatsAppResult:
    status: str
    provider: str
    provider_message_id: str = ""
    error: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    is_uncertain: bool = False

    @property
    def was_transmitted(self) -> bool:
        """Returns True ONLY if the message was submitted to a live provider API."""
        return self.status == WhatsAppStatus.SUBMITTED


def normalize_phone_number(number: str) -> Optional[str]:
    """
    Format a phone number into the format required by Meta WhatsApp Cloud API.

    For Indian numbers: 10-digit number starting with 6, 7, 8, or 9
    Returns E.164 without leading '+': '91XXXXXXXXXX'.
    Returns None if the number cannot be parsed as a valid mobile number.
    """
    if not number:
        return None

    cleaned = re.sub(r"[\s\-\(\)\+]", "", str(number).strip())

    # Strip leading international dialling prefix 00
    if cleaned.startswith("00"):
        cleaned = cleaned[2:]

    # Strip single leading zero
    if cleaned.startswith("0") and len(cleaned) == 11:
        cleaned = cleaned[1:]

    # Strip leading 91 if present and 12 digits
    if cleaned.startswith("91") and len(cleaned) == 12:
        digits = cleaned[2:]
    elif len(cleaned) == 10:
        digits = cleaned
    else:
        return None

    # Validate 10-digit Indian mobile pattern
    if re.fullmatch(r"[6-9]\d{9}", digits):
        return f"91{digits}"

    return None


def mask_phone_number(number: str) -> str:
    """Mask phone number for safe logging (e.g. 9198****3210)."""
    s = str(number).strip()
    if len(s) > 4:
        return s[:4] + "****" + s[-4:]
    return "****"


class BaseWhatsAppBackend:
    """Interface every WhatsApp provider adapter must implement."""

    provider_name = "base"
    is_live = False

    def send_template(
        self,
        to: str,
        template_name: str,
        language_code: str,
        body_parameters: List[str],
        fallback_text: str = "",
        on_before_send: Optional[Any] = None,
        biz_opaque_callback_data: Optional[str] = None,
    ) -> WhatsAppResult:
        raise NotImplementedError("WhatsApp backends must implement send_template().")


class MockWhatsAppBackend(BaseWhatsAppBackend):
    """
    Development & testing backend.

    Simulates successful WhatsApp processing and logs the payload.
    NEVER makes any network calls or sends real messages.
    Returns status WhatsAppStatus.MOCKED so the notification is never marked
    as sent or delivered.
    """

    provider_name = "mock"
    is_live = False

    def send_template(
        self,
        to: str,
        template_name: str,
        language_code: str,
        body_parameters: List[str],
        fallback_text: str = "",
        on_before_send: Optional[Any] = None,
        biz_opaque_callback_data: Optional[str] = None,
    ) -> WhatsAppResult:
        # NOTE: MockWhatsAppBackend NEVER calls on_before_send, because
        # no external transmission takes place.
        normalized = normalize_phone_number(to) or to
        mock_id = f"mock-wa-{uuid.uuid4().hex[:12]}"

        logger.info(
            "MOCK WHATSAPP (not transmitted) to %s | Template: %s [%s] | Params: %s | Message: %s",
            mask_phone_number(normalized),
            template_name,
            language_code,
            body_parameters,
            fallback_text,
        )

        return WhatsAppResult(
            status=WhatsAppStatus.MOCKED,
            provider=self.provider_name,
            provider_message_id=mock_id,
            details={
                "template": template_name,
                "language": language_code,
                "parameters": body_parameters,
                "fallback_text": fallback_text,
                "biz_opaque_callback_data": biz_opaque_callback_data,
            },
        )


class MetaWhatsAppCloudBackend(BaseWhatsAppBackend):
    """
    Official WhatsApp Business Platform (Cloud API) backend using Meta Graph API.

    Endpoint:
      POST https://graph.facebook.com/{version}/{phone_number_id}/messages

    Requires settings / environment variables:
      WHATSAPP_ACCESS_TOKEN         – System user permanent token or temporary token
      WHATSAPP_PHONE_NUMBER_ID     – Meta WhatsApp Phone Number ID
      WHATSAPP_API_VERSION         – e.g. 'v20.0'
    """

    provider_name = "meta_cloud"
    is_live = True
    TIMEOUT = 15  # seconds

    def _get_access_token(self) -> str:
        token = getattr(settings, "WHATSAPP_ACCESS_TOKEN", "") or ""
        if not token:
            raise ValueError("WHATSAPP_ACCESS_TOKEN is not configured in settings.")
        return token

    def _get_phone_number_id(self) -> str:
        phone_id = getattr(settings, "WHATSAPP_PHONE_NUMBER_ID", "") or ""
        if not phone_id:
            raise ValueError("WHATSAPP_PHONE_NUMBER_ID is not configured in settings.")
        return phone_id

    def _get_api_version(self) -> str:
        return getattr(settings, "WHATSAPP_API_VERSION", "v20.0") or "v20.0"

    def _get_api_url(self) -> str:
        version = self._get_api_version()
        phone_id = self._get_phone_number_id()
        return f"https://graph.facebook.com/{version}/{phone_id}/messages"

    def build_payload(
        self,
        to: str,
        template_name: str,
        language_code: str,
        body_parameters: List[str],
        biz_opaque_callback_data: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Construct the Meta Cloud API template message payload."""
        components = []
        if body_parameters:
            parameters = [{"type": "text", "text": str(param)} for param in body_parameters]
            components.append({
                "type": "body",
                "parameters": parameters,
            })

        payload: Dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {
                    "code": language_code,
                },
                "components": components,
            },
        }
        if biz_opaque_callback_data:
            # Meta supports client-generated opaque callback data (up to 512 bytes).
            # This is echoed in webhook delivery events, enabling reliable correlation
            # even when the worker crashes before saving provider_message_id.
            payload["biz_opaque_callback_data"] = str(biz_opaque_callback_data)

        return payload

    def send_template(
        self,
        to: str,
        template_name: str,
        language_code: str,
        body_parameters: List[str],
        fallback_text: str = "",
        on_before_send: Optional[Any] = None,
        biz_opaque_callback_data: Optional[str] = None,
    ) -> WhatsAppResult:
        normalized = normalize_phone_number(to)
        if not normalized:
            error_msg = f"Invalid mobile number format for WhatsApp: {mask_phone_number(to)}"
            logger.error(error_msg)
            return WhatsAppResult(
                status=WhatsAppStatus.FAILED,
                provider=self.provider_name,
                error=error_msg,
            )

        try:
            token = self._get_access_token()
            url = self._get_api_url()
        except ValueError as exc:
            logger.error("Meta WhatsApp configuration error: %s", exc)
            return WhatsAppResult(
                status=WhatsAppStatus.FAILED,
                provider=self.provider_name,
                error=str(exc),
            )

        payload = self.build_payload(
            to=normalized,
            template_name=template_name,
            language_code=language_code,
            body_parameters=body_parameters,
            biz_opaque_callback_data=biz_opaque_callback_data,
        )

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        masked_to = mask_phone_number(normalized)

        # Execute on_before_send hook immediately before the actual live network transmission.
        # This persists the live transmission marker so that worker crashes during or after
        # Meta's request are classified as uncertain.
        if on_before_send and callable(on_before_send):
            try:
                on_before_send()
            except Exception as exc:  # noqa: BLE001
                logger.exception("Error executing on_before_send callback: %s", exc)

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=self.TIMEOUT)

            # Try parsing JSON response
            try:
                data = response.json()
            except Exception:
                data = {"raw_text": response.text[:500]}

            if response.status_code == 200 and isinstance(data, dict):
                # Meta returns: {"messaging_product":"whatsapp","contacts":[{"input":"...","wa_id":"..."}],"messages":[{"id":"wamid.HBg..."}]}
                messages_list = data.get("messages", [])
                provider_msg_id = ""
                if messages_list and isinstance(messages_list, list):
                    provider_msg_id = messages_list[0].get("id", "")

                logger.info(
                    "Meta WhatsApp accepted request for %s, provider_message_id=%s",
                    masked_to,
                    provider_msg_id,
                )

                return WhatsAppResult(
                    status=WhatsAppStatus.SUBMITTED,
                    provider=self.provider_name,
                    provider_message_id=provider_msg_id,
                    details=data,
                )

            # Extract Meta API error message safely without leaking tokens
            error_details = "Unknown Meta API error"
            is_server_error = response.status_code >= 500
            if isinstance(data, dict) and "error" in data:
                err_dict = data["error"]
                err_code = err_dict.get("code", "")
                err_subcode = err_dict.get("error_subcode", "")
                err_user_msg = err_dict.get("error_user_msg") or err_dict.get("message", "")
                error_details = f"Meta API Error ({err_code}/{err_subcode}): {err_user_msg}"
            else:
                error_details = f"HTTP {response.status_code}: {response.text[:300]}"

            logger.error(
                "Meta WhatsApp Cloud API error for %s: %s (uncertain=%s)",
                masked_to, error_details, is_server_error,
            )
            return WhatsAppResult(
                status=WhatsAppStatus.FAILED,
                provider=self.provider_name,
                error=error_details[:500],
                details=data if isinstance(data, dict) else {},
                is_uncertain=is_server_error,
            )

        except requests.exceptions.ReadTimeout:
            # ReadTimeout means HTTP request was sent to Meta, but waiting for response timed out.
            # Meta may have accepted and queued the message for delivery.
            logger.error("Meta WhatsApp Cloud API read timed out for %s (transmission outcome is uncertain)", masked_to)
            return WhatsAppResult(
                status=WhatsAppStatus.FAILED,
                provider=self.provider_name,
                error="Meta WhatsApp Cloud API read timed out. Transmission outcome is uncertain.",
                is_uncertain=True,
            )
        except requests.exceptions.ConnectTimeout:
            # ConnectTimeout means TCP handshake failed before transmitting any payload.
            logger.error("Meta WhatsApp Cloud API connection timed out for %s", masked_to)
            return WhatsAppResult(
                status=WhatsAppStatus.FAILED,
                provider=self.provider_name,
                error="Meta WhatsApp Cloud API connection timed out before transmission.",
                is_uncertain=False,
            )
        except requests.exceptions.SSLError as exc:
            # SSL handshake failed before HTTP payload transmission.
            logger.error("Meta WhatsApp Cloud API SSL handshake error for %s: %s", masked_to, exc)
            return WhatsAppResult(
                status=WhatsAppStatus.FAILED,
                provider=self.provider_name,
                error=f"SSL handshake error: {str(exc)[:200]}",
                is_uncertain=False,
            )
        except requests.Timeout:
            logger.error("Meta WhatsApp Cloud API request timed out for %s (outcome uncertain)", masked_to)
            return WhatsAppResult(
                status=WhatsAppStatus.FAILED,
                provider=self.provider_name,
                error="Meta WhatsApp Cloud API request timed out.",
                is_uncertain=True,
            )
        except requests.ConnectionError as exc:
            # A connection failure must NOT automatically be considered safe to retry
            # unless confirmed that the request was not transmitted.
            is_confirmed_pre_tx = _is_confirmed_pre_transmission_error(exc)
            clean_err = str(exc)[:200]
            logger.error(
                "Meta WhatsApp connection error for %s: %s (confirmed_pre_transmission=%s)",
                masked_to, clean_err, is_confirmed_pre_tx,
            )
            return WhatsAppResult(
                status=WhatsAppStatus.FAILED,
                provider=self.provider_name,
                error=f"Connection error: {clean_err}",
                is_uncertain=not is_confirmed_pre_tx,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected error communicating with Meta WhatsApp for %s", masked_to)
            return WhatsAppResult(
                status=WhatsAppStatus.FAILED,
                provider=self.provider_name,
                error=f"Unexpected error: {str(exc)[:200]}",
                is_uncertain=True,
            )


def _is_confirmed_pre_transmission_error(exc: Exception) -> bool:
    """
    Determine if a connection error is confirmed to have occurred before any HTTP
    payload was transmitted to the remote server.

    Confirmed pre-transmission errors (safe to retry, is_uncertain=False):
      - ConnectTimeout: TCP connection was never established.
      - SSLError: TLS negotiation failed before HTTP payload was sent.
      - DNS lookup failure (socket.gaierror, NameResolutionError).
      - Connection refused (NewConnectionError with ECONNREFUSED).

    Ambiguous connection errors (must NOT be retried automatically, is_uncertain=True):
      - RemoteDisconnected ('Remote end closed connection without response').
      - ConnectionResetError / BrokenPipeError.
      - Connection aborted / dropped mid-transmission.
    """
    if isinstance(exc, (requests.exceptions.SSLError, requests.exceptions.ProxyError, requests.exceptions.ConnectTimeout)):
        return True

    err_str = str(exc).lower()

    # Confirmed pre-connection indicators
    pre_tx_indicators = [
        "failed to resolve",
        "getaddrinfo failed",
        "nameresolutionerror",
        "name or service not known",
        "nodename nor servname provided",
        "connection refused",
        "[errno 111]",
        "[winerror 10061]",
    ]
    for ind in pre_tx_indicators:
        if ind in err_str:
            return True

    # Mid-flight disconnection indicators (bytes may have been sent)
    uncertain_indicators = [
        "remotedisconnected",
        "connection reset",
        "broken pipe",
        "connection aborted",
        "protocolerror",
        "reset by peer",
        "closed connection without response",
    ]
    for ind in uncertain_indicators:
        if ind in err_str:
            return False

    # Check cause recursively
    cause = getattr(exc, "__cause__", None)
    if cause and isinstance(cause, Exception):
        return _is_confirmed_pre_transmission_error(cause)

    # Per requirement: A connection failure must not automatically be considered
    # safe to retry unless confirmed that the request was not transmitted.
    return False


def get_whatsapp_backend() -> BaseWhatsAppBackend:
    """Instantiate the WhatsApp backend specified in settings.WHATSAPP_BACKEND."""
    backend_path = getattr(
        settings,
        "WHATSAPP_BACKEND",
        "notifications.whatsapp.MockWhatsAppBackend",
    )
    return import_string(backend_path)()


def send_whatsapp_template(
    to: str,
    template_name: str,
    language_code: str,
    body_parameters: List[str],
    fallback_text: str = "",
    on_before_send: Optional[Any] = None,
    biz_opaque_callback_data: Optional[str] = None,
) -> WhatsAppResult:
    """
    Public entry point to dispatch a WhatsApp template message.

    Catches any unforeseen backend exceptions so calling transactions
    never crash.
    """
    backend = None
    try:
        backend = get_whatsapp_backend()
        return backend.send_template(
            to=to,
            template_name=template_name,
            language_code=language_code,
            body_parameters=body_parameters,
            fallback_text=fallback_text,
            on_before_send=on_before_send,
            biz_opaque_callback_data=biz_opaque_callback_data,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("WhatsApp template send failed for %s", mask_phone_number(to))
        is_uncertain = False
        if isinstance(exc, (requests.exceptions.ReadTimeout, requests.exceptions.Timeout)):
            is_uncertain = True
        elif isinstance(exc, requests.exceptions.ConnectionError):
            is_uncertain = not _is_confirmed_pre_transmission_error(exc)
        return WhatsAppResult(
            status=WhatsAppStatus.FAILED,
            provider=getattr(backend, "provider_name", "unknown"),
            error=str(exc)[:500],
            is_uncertain=is_uncertain,
        )
