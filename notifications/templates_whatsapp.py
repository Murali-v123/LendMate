"""
WhatsApp message template builders for LendMate.

Each builder produces:
  - template_name: Configurable name matching the approved Meta WhatsApp template
  - language_code: Language code (e.g. 'en')
  - parameters: List of variable parameter strings for Meta's body component
  - rendered_text: Full formatted text representation for local display and database storage

All amounts are formatted in INR (₹) with two decimal places and standard thousands grouping.
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional

from django.conf import settings


@dataclass(frozen=True)
class WhatsAppTemplatePayload:
    template_name: str
    language_code: str
    parameters: List[str]
    rendered_text: str


def _fmt_inr(amount) -> str:
    """Format decimal amount with INR symbol and thousands separator."""
    try:
        val = Decimal(amount)
        return f"\u20b9{val:,.2f}"
    except Exception:
        return f"\u20b9{amount}"


def _format_date(d) -> str:
    """Format date as 'D Mon YYYY' (e.g. '15 Jan 2026') cross-platform."""
    if d is None:
        return "N/A"
    if hasattr(d, "date"):
        d = d.date()
    if hasattr(d, "day") and hasattr(d, "strftime"):
        return f"{d.day} {d.strftime('%b %Y')}"
    return str(d)


def _lender_name(lender_user) -> str:
    """Return lender full name or username fallback."""
    if lender_user:
        name = lender_user.get_full_name().strip()
        return name if name else lender_user.get_username()
    return "your lender"


def build_loan_created_payload(loan) -> WhatsAppTemplatePayload:
    """
    Template: lendmate_loan_created
    Parameters:
      {{1}}: Borrower full name
      {{2}}: Principal amount (₹X,XXX.XX)
      {{3}}: Lender full name
      {{4}}: Lending date (e.g. 15 Jan 2026)
      {{5}}: Interest description (e.g. '2.00% Monthly')
      {{6}}: Due date (e.g. 15 Jan 2027)
    """
    template_name = getattr(settings, "WHATSAPP_TEMPLATE_LOAN_CREATED", "lendmate_loan_created")
    language_code = getattr(settings, "WHATSAPP_TEMPLATE_LANGUAGE", "en")

    borrower_name = loan.borrower.full_name
    principal_str = _fmt_inr(loan.principal)
    lender_name_str = _lender_name(loan.borrower.lender)
    date_str = _format_date(loan.lending_date)
    interest_str = f"{Decimal(loan.interest_rate):,.2f}% {loan.get_interest_period_display()}"
    due_str = _format_date(loan.due_date) if loan.due_date else "Not set"

    parameters = [
        borrower_name,
        principal_str,
        lender_name_str,
        date_str,
        interest_str,
        due_str,
    ]

    rendered_text = (
        f"Hello {borrower_name}, a loan of {principal_str} has been recorded "
        f"by {lender_name_str} on {date_str}. Interest: {interest_str}. "
        f"Expected return date: {due_str}. "
        f"Please contact your lender for details."
    )

    return WhatsAppTemplatePayload(
        template_name=template_name,
        language_code=language_code,
        parameters=parameters,
        rendered_text=rendered_text,
    )


def build_monthly_reminder_payload(loan, due_date, monthly_amount) -> WhatsAppTemplatePayload:
    """
    Template: lendmate_monthly_reminder
    Parameters:
      {{1}}: Borrower full name
      {{2}}: Lender full name
      {{3}}: Scheduled payment amount (₹X,XXX.XX)
      {{4}}: Due date (e.g. 15 Nov 2026)
    """
    template_name = getattr(settings, "WHATSAPP_TEMPLATE_MONTHLY_REMINDER", "lendmate_monthly_reminder")
    language_code = getattr(settings, "WHATSAPP_TEMPLATE_LANGUAGE", "en")

    borrower_name = loan.borrower.full_name
    lender_name_str = _lender_name(loan.borrower.lender)
    amount_str = _fmt_inr(monthly_amount)
    due_str = _format_date(due_date)

    parameters = [
        borrower_name,
        lender_name_str,
        amount_str,
        due_str,
    ]

    rendered_text = (
        f"Hello {borrower_name}, this is a reminder regarding your loan with {lender_name_str}. "
        f"Your scheduled payment of {amount_str} is due on {due_str}. "
        f"Please contact your lender if you have already made the payment."
    )

    return WhatsAppTemplatePayload(
        template_name=template_name,
        language_code=language_code,
        parameters=parameters,
        rendered_text=rendered_text,
    )


def build_payment_received_payload(payment) -> WhatsAppTemplatePayload:
    """
    Template: lendmate_payment_received
    Parameters:
      {{1}}: Borrower full name
      {{2}}: Payment amount (₹X,XXX.XX)
      {{3}}: Payment date (e.g. 07 Nov 2026)
      {{4}}: Principal component paid (₹X,XXX.XX)
      {{5}}: Interest component paid (₹X,XXX.XX)
      {{6}}: Remaining principal balance (₹X,XXX.XX)
    """
    template_name = getattr(settings, "WHATSAPP_TEMPLATE_PAYMENT_RECEIVED", "lendmate_payment_received")
    language_code = getattr(settings, "WHATSAPP_TEMPLATE_LANGUAGE", "en")

    loan = payment.loan
    borrower_name = loan.borrower.full_name
    amount_str = _fmt_inr(payment.amount)
    date_str = _format_date(payment.payment_date)
    principal_paid_str = _fmt_inr(payment.principal_component)
    interest_paid_str = _fmt_inr(payment.interest_component)
    remaining_str = _fmt_inr(loan.outstanding_principal)

    parameters = [
        borrower_name,
        amount_str,
        date_str,
        principal_paid_str,
        interest_paid_str,
        remaining_str,
    ]

    rendered_text = (
        f"Hello {borrower_name}, your payment of {amount_str} has been recorded on {date_str}. "
        f"Principal paid: {principal_paid_str}. Interest paid: {interest_paid_str}. "
        f"Remaining principal: {remaining_str}. Thank you."
    )

    return WhatsAppTemplatePayload(
        template_name=template_name,
        language_code=language_code,
        parameters=parameters,
        rendered_text=rendered_text,
    )


def build_overdue_reminder_payload(loan, due_date, monthly_amount) -> WhatsAppTemplatePayload:
    """
    Template: lendmate_overdue_reminder
    Parameters:
      {{1}}: Borrower full name
      {{2}}: Scheduled amount (₹X,XXX.XX)
      {{3}}: Due date (e.g. 15 Oct 2026)
      {{4}}: Lender full name
    """
    template_name = getattr(settings, "WHATSAPP_TEMPLATE_OVERDUE_REMINDER", "lendmate_overdue_reminder")
    language_code = getattr(settings, "WHATSAPP_TEMPLATE_LANGUAGE", "en")

    borrower_name = loan.borrower.full_name
    amount_str = _fmt_inr(monthly_amount)
    due_str = _format_date(due_date)
    lender_name_str = _lender_name(loan.borrower.lender)

    parameters = [
        borrower_name,
        amount_str,
        due_str,
        lender_name_str,
    ]

    rendered_text = (
        f"Hello {borrower_name}, our records show that your scheduled payment of "
        f"{amount_str} was due on {due_str}. Please contact {lender_name_str} to "
        f"discuss the payment status."
    )

    return WhatsAppTemplatePayload(
        template_name=template_name,
        language_code=language_code,
        parameters=parameters,
        rendered_text=rendered_text,
    )


def build_loan_closed_payload(loan) -> WhatsAppTemplatePayload:
    """
    Template: lendmate_loan_closed
    Parameters:
      {{1}}: Borrower full name
      {{2}}: Lender full name
    """
    template_name = getattr(settings, "WHATSAPP_TEMPLATE_LOAN_CLOSED", "lendmate_loan_closed")
    language_code = getattr(settings, "WHATSAPP_TEMPLATE_LANGUAGE", "en")

    borrower_name = loan.borrower.full_name
    lender_name_str = _lender_name(loan.borrower.lender)

    parameters = [
        borrower_name,
        lender_name_str,
    ]

    rendered_text = (
        f"Hello {borrower_name}, your loan with {lender_name_str} has been marked as closed. "
        f"Thank you. Please contact your lender if you need clarification about your payment records."
    )

    return WhatsAppTemplatePayload(
        template_name=template_name,
        language_code=language_code,
        parameters=parameters,
        rendered_text=rendered_text,
    )
