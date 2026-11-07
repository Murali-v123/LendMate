"""
SMS message template builder.

All template functions receive domain objects and return a plain-text
string ready to send.  Values are populated from real database records.
Missing optional fields are handled safely with sensible fallbacks.
"""
import datetime
from decimal import Decimal


def _lender_name(loan):
    """Return a display name for the lender, with safe fallback."""
    user = loan.borrower.lender
    if user:
        name = user.get_full_name().strip()
        return name if name else user.get_username()
    return "your lender"


def _format_date(d):
    """Format a date or datetime object as 'D Mon YYYY' (e.g. '15 Jan 2026') cross-platform."""
    if d is None:
        return "N/A"
    if hasattr(d, "date"):
        d = d.date()
    if hasattr(d, "day") and hasattr(d, "strftime"):
        return f"{d.day} {d.strftime('%b %Y')}"
    return str(d)


def _fmt(amount):
    """Format a Decimal amount with two decimal places and commas."""
    try:
        return f"{Decimal(amount):,.2f}"
    except Exception:
        return str(amount)


def build_loan_created_message(loan):
    """
    Hello [Borrower Name], a loan of ₹[Principal] has been recorded by
    [Lender Name] on [Date]. Interest: [Rate]% [Monthly/Annual].
    Expected return date: [Due Date]. Please contact your lender for details.
    """
    borrower_name = loan.borrower.full_name
    principal = _fmt(loan.principal)
    lender = _lender_name(loan)
    date_str = _format_date(loan.lending_date)
    rate = _fmt(loan.interest_rate)
    period = loan.get_interest_period_display()  # "Monthly" or "Annually"
    due_str = _format_date(loan.due_date) if loan.due_date else "not set"

    return (
        f"Hello {borrower_name}, a loan of \u20b9{principal} has been recorded "
        f"by {lender} on {date_str}. Interest: {rate}% {period}. "
        f"Expected return date: {due_str}. "
        f"Please contact your lender for details."
    )


def build_payment_received_message(payment):
    """
    Hello [Borrower Name], your payment of ₹[Amount] has been recorded on
    [Date]. Principal paid: ₹[Principal]. Interest paid: ₹[Interest].
    Remaining principal: ₹[Balance]. Thank you.
    """
    loan = payment.loan
    borrower_name = loan.borrower.full_name
    amount = _fmt(payment.amount)
    date_str = _format_date(payment.payment_date)
    principal_paid = _fmt(payment.principal_component)
    interest_paid = _fmt(payment.interest_component)
    remaining = _fmt(loan.outstanding_principal)

    return (
        f"Hello {borrower_name}, your payment of \u20b9{amount} has been recorded "
        f"on {date_str}. Principal paid: \u20b9{principal_paid}. "
        f"Interest paid: \u20b9{interest_paid}. "
        f"Remaining principal: \u20b9{remaining}. Thank you."
    )


def build_monthly_reminder_message(loan, due_date, monthly_amount):
    """
    Hello [Borrower Name], this is a reminder regarding your loan with
    [Lender Name]. Your scheduled payment of ₹[Amount] is due on [Due Date].
    Please contact your lender if you have already made the payment.
    """
    borrower_name = loan.borrower.full_name
    lender = _lender_name(loan)
    amount = _fmt(monthly_amount)
    due_str = _format_date(due_date)

    return (
        f"Hello {borrower_name}, this is a reminder regarding your loan "
        f"with {lender}. Your scheduled payment of \u20b9{amount} is due on "
        f"{due_str}. Please contact your lender if you have already made "
        f"the payment."
    )


def build_overdue_reminder_message(loan, due_date, monthly_amount):
    """
    Hello [Borrower Name], our records show that your scheduled payment of
    ₹[Amount] was due on [Due Date]. Please contact [Lender Name] to discuss
    the payment status.
    """
    borrower_name = loan.borrower.full_name
    lender = _lender_name(loan)
    amount = _fmt(monthly_amount)
    due_str = _format_date(due_date)

    return (
        f"Hello {borrower_name}, our records show that your scheduled payment "
        f"of \u20b9{amount} was due on {due_str}. Please contact {lender} to "
        f"discuss the payment status."
    )


def build_loan_closed_message(loan):
    """
    Hello [Borrower Name], your loan with [Lender Name] has been marked as
    closed. Thank you. Please contact your lender if you need clarification
    about your payment records.
    """
    borrower_name = loan.borrower.full_name
    lender = _lender_name(loan)

    return (
        f"Hello {borrower_name}, your loan with {lender} has been marked as "
        f"closed. Thank you. Please contact your lender if you need "
        f"clarification about your payment records."
    )
