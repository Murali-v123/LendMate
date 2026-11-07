"""
Notification history and Meta WhatsApp webhook views.

All history queries are scoped to the authenticated lender.
No other lender's notifications are ever exposed.

The Meta WhatsApp webhook handles delivery reports securely with:
- Hub verification token challenge (GET)
- HMAC-SHA256 signature verification (POST)
- Idempotent status transitions (SUBMITTED -> DELIVERED / FAILED)
"""
import hashlib
import hmac
import json
import logging
from typing import Optional

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST

from .models import Notification

logger = logging.getLogger(__name__)

NOTIFICATIONS_PER_PAGE = 25


@login_required
def notification_history(request):
    """Display paginated notification history for the logged-in lender."""
    status_filter = request.GET.get("status", "all").strip().lower()

    valid_statuses = {
        Notification.MOCKED,
        Notification.SUBMITTED,
        Notification.DELIVERED,
        Notification.PENDING,
        Notification.PROCESSING,
        Notification.FAILED,
        Notification.SUPPRESSED,
    }

    qs = (
        Notification.objects
        .filter(lender=request.user)
        .select_related("borrower", "loan")
        .order_by("-created_at")
    )

    if status_filter in valid_statuses:
        qs = qs.filter(status=status_filter)

    paginator = Paginator(qs, NOTIFICATIONS_PER_PAGE)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    # Counts for filter badges
    user_notifications = Notification.objects.filter(lender=request.user)
    counts = {
        "all": user_notifications.count(),
        "mocked": user_notifications.filter(status=Notification.MOCKED).count(),
        "submitted": user_notifications.filter(status=Notification.SUBMITTED).count(),
        "delivered": user_notifications.filter(status=Notification.DELIVERED).count(),
        "pending": user_notifications.filter(status__in=[Notification.PENDING, Notification.PROCESSING]).count(),
        "failed": user_notifications.filter(status=Notification.FAILED).count(),
        "suppressed": user_notifications.filter(status=Notification.SUPPRESSED).count(),
    }

    context = {
        "page_obj": page_obj,
        "status_filter": status_filter,
        "counts": counts,
    }
    return render(request, "notifications/history.html", context)


@login_required
@require_POST
def retry_notification(request, pk: int):
    """
    Manually retry a failed notification.
    Only the owning lender can retry their own notifications.
    """
    notification = get_object_or_404(
        Notification,
        pk=pk,
        lender=request.user,
    )

    if notification.status != Notification.FAILED:
        messages.warning(
            request,
            f"Notification #{pk} is not in a failed state and cannot be retried.",
        )
        return redirect("notifications:history")

    if notification.attempts >= 5:
        messages.error(
            request,
            f"Notification #{pk} has exhausted all retry attempts. Create a new notification if needed.",
        )
        return redirect("notifications:history")

    # Reset for retry
    notification.status = Notification.PENDING
    notification.last_error = ""
    notification.next_retry_at = None
    notification.save(update_fields=["status", "last_error", "next_retry_at", "updated_at"])

    try:
        from .tasks import send_whatsapp_notification  # noqa: PLC0415
        send_whatsapp_notification.delay(notification.pk)
        messages.success(request, f"Notification #{pk} has been queued for retry.")
    except Exception:  # noqa: BLE001
        messages.warning(
            request,
            f"Notification #{pk} reset to pending, but Celery may be unavailable. "
            "It will be processed when the worker recovers.",
        )

    return redirect("notifications:history")


# ---------------------------------------------------------------------------
# Meta WhatsApp Delivery Webhook
# ---------------------------------------------------------------------------

def _verify_webhook_signature(payload_bytes: bytes, signature_header: str) -> bool:
    """Validate X-Hub-Signature-256 against WHATSAPP_APP_SECRET."""
    app_secret = getattr(settings, "WHATSAPP_APP_SECRET", "") or ""
    if not app_secret:
        logger.error("WHATSAPP_APP_SECRET is not configured; rejecting webhook request for security.")
        return False

    if not signature_header or not signature_header.startswith("sha256="):
        logger.warning("Missing or malformed X-Hub-Signature-256 header.")
        return False

    expected_signature = signature_header.split("sha256=", 1)[1]
    calculated_signature = hmac.new(
        app_secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(calculated_signature, expected_signature)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def whatsapp_webhook(request):
    """
    Official Meta WhatsApp Business Cloud API webhook endpoint.

    GET: Webhook verification challenge
    POST: Delivery and read receipts status updates
    """
    if request.method == "GET":
        mode = request.GET.get("hub.mode")
        verify_token = request.GET.get("hub.verify_token")
        challenge = request.GET.get("hub.challenge")

        configured_token = getattr(settings, "WHATSAPP_VERIFY_TOKEN", "") or ""

        if mode == "subscribe" and configured_token and verify_token == configured_token:
            logger.info("Meta WhatsApp webhook verified successfully.")
            return HttpResponse(challenge, content_type="text/plain", status=200)

        logger.warning(
            "Meta WhatsApp webhook verification failed. mode=%s, token_match=%s",
            mode,
            bool(configured_token and verify_token == configured_token),
        )
        return HttpResponseForbidden("Verification token mismatch.")

    # POST: Process delivery status updates
    signature = request.META.get("HTTP_X_HUB_SIGNATURE_256", "")
    if not _verify_webhook_signature(request.body, signature):
        logger.warning("Meta WhatsApp webhook rejected due to invalid signature.")
        return HttpResponseForbidden("Invalid signature.")

    try:
        data = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        logger.error("Meta WhatsApp webhook received invalid JSON payload.")
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    # Process status updates from Meta payload:
    # entry -> changes -> value -> statuses
    entries = data.get("entry", [])
    for entry in entries:
        changes = entry.get("changes", [])
        for change in changes:
            value = change.get("value", {})
            statuses = value.get("statuses", [])
            for status_item in statuses:
                wamid = status_item.get("id")
                status_str = status_item.get("status")  # sent, delivered, read, failed
                if not wamid or not status_str:
                    continue

                _handle_status_update(wamid, status_str, status_item)

    return JsonResponse({"status": "received"})


def _parse_notification_id_from_callback_data(callback_data: str) -> Optional[int]:
    """
    Extract notification primary key from Meta's biz_opaque_callback_data.
    Supported formats: 'notif_123', '123'.
    """
    if not callback_data:
        return None
    try:
        raw = str(callback_data).strip()
        if raw.startswith("notif_"):
            raw = raw.split("notif_", 1)[1]
        return int(raw)
    except (ValueError, TypeError):
        return None


def _apply_status_transition(notification: Notification, status_str: str, status_item: dict, wamid: str = ""):
    """
    Apply explicit, safe status transitions to a Notification instance.

    Guarantees:
      - DELIVERED is terminal success: never downgraded by late 'sent' or late 'failed'.
      - FAILED is terminal failure: never downgraded to SUBMITTED by a late 'sent'.
      - Duplicate delivery events are safe no-ops.
      - Out-of-order events do not corrupt notification history.
    """
    current = notification.status

    # Rule 1: DELIVERED is terminal success. Never downgrade.
    if current == Notification.DELIVERED:
        if status_str in ("delivered", "read"):
            logger.debug("Notification %s is already DELIVERED; duplicate '%s' event ignored.", notification.pk, status_str)
        elif status_str == "sent":
            logger.info("Notification %s is already DELIVERED; ignoring out-of-order 'sent' event.", notification.pk)
        elif status_str == "failed":
            logger.warning("Notification %s is already DELIVERED; ignoring out-of-order 'failed' event.", notification.pk)
        return

    # Rule 2: FAILED status must NOT be downgraded to SUBMITTED by a late 'sent' event.
    if current == Notification.FAILED and status_str == "sent":
        logger.info(
            "Notification %s is in status FAILED; ignoring late 'sent' event to prevent status downgrade.",
            notification.pk,
        )
        return

    # Rule 3: Delivered or read transitions to DELIVERED
    if status_str in ("delivered", "read"):
        notification.status = Notification.DELIVERED
        notification.last_error = ""
        notification.save(update_fields=["status", "last_error", "updated_at"])
        logger.info("Notification %s marked DELIVERED via webhook (status=%s)", notification.pk, status_str)
        return

    # Rule 4: Failed transitions to FAILED
    if status_str == "failed":
        notification.status = Notification.FAILED
        errors = status_item.get("errors", [])
        err_msg = "Delivery failed"
        if errors and isinstance(errors, list):
            first_err = errors[0]
            err_msg = f"Delivery failed ({first_err.get('code')}: {first_err.get('title')})"
        notification.last_error = err_msg[:500]
        notification.save(update_fields=["status", "last_error", "updated_at"])
        logger.warning("Notification %s marked FAILED via webhook: %s", notification.pk, err_msg)
        return

    # Rule 5: 'sent' event confirms provider transmission
    if status_str == "sent":
        # Only transition if not already SUBMITTED or DELIVERED
        if current not in (Notification.SUBMITTED, Notification.DELIVERED):
            notification.status = Notification.SUBMITTED
            notification.save(update_fields=["status", "updated_at"])
            logger.info("Notification %s marked SUBMITTED via webhook ('sent')", notification.pk)
        return


def _handle_status_update(wamid: str, status_str: str, status_item: dict):
    """
    Update notification status safely based on Meta delivery reports.

    Uses row-level locking (select_for_update) to handle concurrent webhook
    deliveries safely. Correlates via provider_message_id and Meta's
    biz_opaque_callback_data, ensuring recovery even if the Celery worker
    crashed before persisting provider_message_id.
    """
    from .models import UnmatchedWebhookEvent  # noqa: PLC0415
    from django.db import transaction  # noqa: PLC0415

    with transaction.atomic():
        notification = (
            Notification.objects
            .select_for_update()
            .filter(provider_message_id=wamid)
            .first()
        )

        callback_data = status_item.get("biz_opaque_callback_data") or ""
        if not notification and callback_data:
            notif_id = _parse_notification_id_from_callback_data(callback_data)
            if notif_id:
                notification = (
                    Notification.objects
                    .select_for_update()
                    .filter(pk=notif_id)
                    .first()
                )
                if notification and not notification.provider_message_id:
                    # Webhook arrived before or during worker persistence / crash recovery
                    notification.provider_message_id = wamid
                    notification.save(update_fields=["provider_message_id", "updated_at"])
                    logger.info(
                        "Correlated notification %s with provider_message_id %s via biz_opaque_callback_data",
                        notification.pk, wamid,
                    )

        if not notification:
            # Unmatched webhook event: do NOT discard! Store in UnmatchedWebhookEvent for recovery.
            logger.warning(
                "Received WhatsApp webhook for unknown provider_message_id %s (status=%s). "
                "Storing in UnmatchedWebhookEvent for recovery replay.",
                wamid, status_str,
            )
            UnmatchedWebhookEvent.objects.update_or_create(
                provider_message_id=wamid,
                defaults={
                    "status": status_str,
                    "callback_data": callback_data,
                    "payload": status_item,
                    "resolved": False,
                },
            )
            return

        # Apply safe status transitions
        _apply_status_transition(notification, status_str, status_item, wamid)


def replay_unmatched_webhooks_for_notification(notification: Notification) -> bool:
    """
    Check if any UnmatchedWebhookEvent exists for notification.provider_message_id,
    apply the status updates, and mark the events as resolved.
    """
    from .models import UnmatchedWebhookEvent  # noqa: PLC0415
    if not notification.provider_message_id:
        return False

    events = UnmatchedWebhookEvent.objects.filter(
        provider_message_id=notification.provider_message_id,
        resolved=False,
    ).order_by("created_at")

    if not events.exists():
        return False

    for event in events:
        _apply_status_transition(notification, event.status, event.payload, event.provider_message_id)
        event.resolved = True
        event.save(update_fields=["resolved"])
        logger.info(
            "Replayed unmatched webhook event %s for notification %s (status=%s)",
            event.pk, notification.pk, event.status,
        )

    return True
