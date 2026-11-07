import calendar
import datetime
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import models, transaction
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import (
    BorrowerForm,
    LoanForm,
    PaymentForm,
    BorrowerTrackerForm,
    AutomaticTrackerForm,
    ExtendTrackerForm,
    TrackerItemForm,
)
from .models import Borrower, Loan, Payment, BorrowerTracker, TrackerItem


def _safe_enqueue(fn, *args, **kwargs):
    """Call a notification enqueue function without letting it crash the caller."""
    try:
        fn(*args, **kwargs)
    except Exception:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception(
            "WhatsApp notification enqueue failed (non-fatal): %s", fn.__name__
        )


# --- Helpers for Automatic Monthly Trackers ---


def get_monthly_sequence(start_date, end_date):
    """
    Returns list of dicts:
    [{'year': 2026, 'month': 11, 'title': 'November 2026', 'date': date(2026, 11, 1)}, ...]
    Inclusive of start and end months. Handles leap years and month ends safely.
    """
    if not start_date or not end_date:
        return []

    cur_year = start_date.year
    cur_month = start_date.month

    end_year = end_date.year
    end_month = end_date.month

    if (end_year, end_month) < (cur_year, cur_month):
        end_year, end_month = cur_year, cur_month

    months = []
    while (cur_year < end_year) or (cur_year == end_year and cur_month <= end_month):
        rep_date = datetime.date(cur_year, cur_month, 1)
        months.append({
            "year": cur_year,
            "month": cur_month,
            "title": rep_date.strftime("%B %Y"),
            "date": rep_date,
        })
        if cur_month == 12:
            cur_month = 1
            cur_year += 1
        else:
            cur_month += 1

    return months


def add_months_to_date(base_date, months_to_add):
    """
    Adds months_to_add months to base_date safely, clamping to end of month if necessary.
    """
    new_year = base_date.year + (base_date.month + months_to_add - 1) // 12
    new_month = (base_date.month + months_to_add - 1) % 12 + 1
    max_days = calendar.monthrange(new_year, new_month)[1]
    new_day = min(base_date.day, max_days)
    return datetime.date(new_year, new_month, new_day)


# --- Borrower Views ---


@login_required
def add_borrower(request):
    if request.method == "POST":
        form = BorrowerForm(request.POST)

        if form.is_valid():
            borrower = form.save(commit=False)
            borrower.lender = request.user
            borrower.save()

            messages.success(request, "Borrower added successfully!")
            return redirect("lending:borrower_detail", pk=borrower.pk)

    else:
        form = BorrowerForm()

    return render(request, "lending/add_borrower.html", {"form": form})


@login_required
def edit_borrower(request, pk):
    borrower = get_object_or_404(Borrower, pk=pk, lender=request.user)

    if request.method == "POST":
        form = BorrowerForm(request.POST, instance=borrower)
        if form.is_valid():
            form.save()
            messages.success(request, f"Profile for {borrower.full_name} updated successfully.")
            return redirect("lending:borrower_detail", pk=borrower.pk)
    else:
        form = BorrowerForm(instance=borrower)

    return render(
        request,
        "lending/edit_borrower.html",
        {
            "form": form,
            "borrower": borrower,
        },
    )


@login_required
def borrower_list(request):
    query = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "all").strip().lower()

    borrowers = Borrower.objects.filter(lender=request.user)

    if query:
        borrowers = borrowers.filter(
            models.Q(full_name__icontains=query) | models.Q(mobile_number__icontains=query)
        )

    if status_filter == "active":
        borrowers = borrowers.filter(loans__status="open").distinct()
    elif status_filter == "inactive":
        active_ids = Borrower.objects.filter(
            lender=request.user,
            loans__status="open",
        ).values_list("id", flat=True)
        borrowers = borrowers.exclude(id__in=active_ids)

    borrowers = borrowers.prefetch_related(
        "loans", "loans__payments"
    ).order_by("-created_at")

    total_count = Borrower.objects.filter(lender=request.user).count()

    context = {
        "borrowers": borrowers,
        "query": query,
        "status_filter": status_filter,
        "total_count": total_count,
    }

    return render(request, "lending/borrower_list.html", context)


@login_required
def borrower_detail(request, pk):
    borrower = get_object_or_404(
        Borrower.objects.filter(lender=request.user),
        pk=pk,
    )

    loans = borrower.loans.prefetch_related("payments").order_by("-created_at")

    payments = (
        Payment.objects.filter(loan__borrower=borrower)
        .select_related("loan")
        .order_by("-payment_date", "-created_at")
    )

    trackers = borrower.trackers.prefetch_related("items", "loan").all()

    tracker_form = BorrowerTrackerForm()
    auto_tracker_form = AutomaticTrackerForm(borrower=borrower, lender=request.user)
    extend_form = ExtendTrackerForm()
    item_form = TrackerItemForm()

    # Loans that do not yet have a due date (for user guidance)
    loans_missing_due_date = loans.filter(due_date__isnull=True)

    context = {
        "borrower": borrower,
        "loans": loans,
        "loans_missing_due_date": loans_missing_due_date,
        "payments": payments,
        "trackers": trackers,
        "tracker_form": tracker_form,
        "auto_tracker_form": auto_tracker_form,
        "extend_form": extend_form,
        "item_form": item_form,
        "total_loans": borrower.total_loans_count,
        "total_borrowed": borrower.total_borrowed,
        "outstanding_principal": borrower.outstanding_principal,
        "active_loans": borrower.active_loans_count,
        "closed_loans": borrower.closed_loans_count,
    }

    return render(request, "lending/borrower_detail.html", context)


# --- Loan Views ---


@login_required
def add_loan(request):
    borrower_id = request.GET.get("borrower")
    initial_borrower = None
    if borrower_id:
        initial_borrower = Borrower.objects.filter(
            pk=borrower_id, lender=request.user
        ).first()

    if request.method == "POST":
        form = LoanForm(request.POST, lender=request.user)

        if form.is_valid():
            loan = form.save()
            messages.success(request, "Loan created successfully!")

            # Enqueue loan-created notification (non-fatal if it fails)
            from notifications.service import enqueue_loan_created  # noqa: PLC0415
            _safe_enqueue(enqueue_loan_created, loan)

            return redirect("lending:loan_detail", loan_id=loan.loan_id)

    else:
        form = LoanForm(lender=request.user, borrower=initial_borrower)

    return render(request, "lending/add_loan.html", {"form": form})


@login_required
def loan_list(request):
    loans = (
        Loan.objects.filter(borrower__lender=request.user)
        .select_related("borrower")
        .order_by("-created_at")
    )

    return render(request, "lending/loan_list.html", {"loans": loans})


@login_required
def loan_detail(request, loan_id):
    loan = get_object_or_404(
        Loan.objects.select_related("borrower"),
        loan_id=loan_id,
        borrower__lender=request.user,
    )

    payments = loan.payments.order_by("-payment_date", "-created_at")

    return render(
        request,
        "lending/loan_detail.html",
        {
            "loan": loan,
            "payments": payments,
        },
    )


@login_required
def add_payment(request, loan_id=None):
    loan = None

    if loan_id:
        loan = get_object_or_404(
            Loan,
            loan_id=loan_id,
            borrower__lender=request.user,
            status="open",
        )

    if request.method == "POST":
        form = PaymentForm(
            request.POST,
            lender=request.user,
            loan=loan,
        )

        if form.is_valid():
            payment = form.save()

            messages.success(
                request,
                "Payment recorded successfully!",
            )

            # Enqueue payment-received notification (non-fatal if it fails)
            from notifications.service import enqueue_payment_received  # noqa: PLC0415
            _safe_enqueue(enqueue_payment_received, payment)

            return redirect(
                "lending:loan_detail",
                loan_id=payment.loan.loan_id,
            )

    else:
        form = PaymentForm(
            lender=request.user,
            loan=loan,
        )

    return render(
        request,
        "lending/add_payment.html",
        {
            "form": form,
            "loan": loan,
        },
    )


# --- Loan Closing and Reopening ---


@login_required
@require_POST
def close_loan(request, loan_id):
    loan = get_object_or_404(
        Loan,
        loan_id=loan_id,
        borrower__lender=request.user,
    )

    if loan.status == "open":
        loan.status = "closed"
        loan.closed_at = timezone.now()
        loan.save(update_fields=["status", "closed_at"])
        messages.success(request, f"Loan {loan.loan_id} has been marked as closed.")

        # Enqueue loan-closed notification (non-fatal if it fails)
        from notifications.service import enqueue_loan_closed  # noqa: PLC0415
        _safe_enqueue(enqueue_loan_closed, loan)
    else:
        messages.info(request, "Loan is already closed.")

    return redirect("lending:loan_detail", loan_id=loan.loan_id)


@login_required
@require_POST
def reopen_loan(request, loan_id):
    loan = get_object_or_404(
        Loan,
        loan_id=loan_id,
        borrower__lender=request.user,
    )

    if loan.status == "closed":
        loan.status = "open"
        loan.closed_at = None
        loan.save(update_fields=["status", "closed_at"])
        messages.success(request, f"Loan {loan.loan_id} has been reopened.")
    else:
        messages.info(request, "Loan is already open.")

    return redirect("lending:loan_detail", loan_id=loan.loan_id)


# --- Tracker Views (Custom + Automatic) ---


@login_required
@require_POST
def create_tracker(request, borrower_id):
    """Creates a standard custom tracker with manual items."""
    borrower = get_object_or_404(Borrower, pk=borrower_id, lender=request.user)
    form = BorrowerTrackerForm(request.POST)

    if form.is_valid():
        tracker = form.save(commit=False)
        tracker.borrower = borrower
        tracker.tracker_type = "custom"
        tracker.save()
        messages.success(request, f'Custom tracker "{tracker.title}" created successfully.')
    else:
        messages.error(request, "Unable to create custom tracker. Title is required.")

    return redirect("lending:borrower_detail", pk=borrower.pk)


@login_required
@require_POST
def create_automatic_tracker(request, borrower_id):
    """
    Creates an automatic monthly tracker generated from a loan's lending date to expected return date.
    """
    borrower = get_object_or_404(Borrower, pk=borrower_id, lender=request.user)
    form = AutomaticTrackerForm(request.POST, borrower=borrower, lender=request.user)

    if not form.is_valid():
        for field, errors in form.errors.items():
            for error in errors:
                messages.error(request, error)
        return redirect("lending:borrower_detail", pk=borrower.pk)

    loan = form.cleaned_data["loan"]

    # Prevent duplicate automatic tracker for the exact same loan
    if BorrowerTracker.objects.filter(borrower=borrower, loan=loan, tracker_type="automatic").exists():
        messages.warning(
            request,
            f"An automatic monthly tracker already exists for Loan #{str(loan.loan_id)[:8]}."
        )
        return redirect("lending:borrower_detail", pk=borrower.pk)

    start_date = loan.lending_date
    end_date = loan.due_date

    user_title = form.cleaned_data.get("title")
    title = user_title if user_title else f"Monthly Tracker – Loan #{str(loan.loan_id)[:8]}"

    description = form.cleaned_data.get("description")
    if not description:
        description = (
            f"Automated monthly tracking for Loan #{str(loan.loan_id)[:8]} "
            f"(Principal: ₹{loan.principal:,.2f}, {start_date.strftime('%b %Y')} to {end_date.strftime('%b %Y')})."
        )

    with transaction.atomic():
        tracker = BorrowerTracker.objects.create(
            borrower=borrower,
            loan=loan,
            tracker_type="automatic",
            title=title,
            description=description,
            start_date=start_date,
            end_date=end_date,
        )

        month_sequence = get_monthly_sequence(start_date, end_date)
        items_to_create = [
            TrackerItem(
                tracker=tracker,
                title=month_info["title"],
                tracking_date=month_info["date"],
            )
            for month_info in month_sequence
        ]
        TrackerItem.objects.bulk_create(items_to_create)

    messages.success(
        request,
        f'Automatic monthly tracker "{tracker.title}" generated with {len(month_sequence)} tracking months '
        f'({start_date.strftime("%B %Y")} to {end_date.strftime("%B %Y")}).'
    )
    return redirect("lending:borrower_detail", pk=borrower.pk)


@login_required
@require_POST
def extend_tracker(request, tracker_id):
    """
    Extends an automatic monthly tracker by N months without modifying historical entries.
    Optionally updates the related loan's due date if explicitly requested.
    """
    tracker = get_object_or_404(
        BorrowerTracker,
        pk=tracker_id,
        borrower__lender=request.user,
    )

    if not tracker.is_automatic:
        messages.error(request, "Only automatic monthly trackers can be extended.")
        return redirect("lending:borrower_detail", pk=tracker.borrower.pk)

    form = ExtendTrackerForm(request.POST)
    if not form.is_valid():
        for field, errors in form.errors.items():
            for error in errors:
                messages.error(request, error)
        return redirect("lending:borrower_detail", pk=tracker.borrower.pk)

    months_to_add = form.get_months_to_add()
    update_loan_due_date = form.cleaned_data.get("update_loan_due_date", False)

    # Base current end date on tracker.end_date, or latest tracking_date, or start_date
    latest_item_date = tracker.items.aggregate(models.Max("tracking_date"))["tracking_date__max"]
    current_end = tracker.end_date or latest_item_date or tracker.start_date or timezone.now().date()

    new_end_date = add_months_to_date(current_end, months_to_add)

    # Identify existing (year, month) pairs to never create duplicates
    existing_months = set()
    for item in tracker.items.all():
        if item.tracking_date:
            existing_months.add((item.tracking_date.year, item.tracking_date.month))

    # Next month after current_end
    start_extend_date = add_months_to_date(current_end, 1)
    extend_sequence = get_monthly_sequence(start_extend_date, new_end_date)

    new_items = []
    for m in extend_sequence:
        if (m["year"], m["month"]) not in existing_months:
            new_items.append(
                TrackerItem(
                    tracker=tracker,
                    title=m["title"],
                    tracking_date=m["date"],
                )
            )

    with transaction.atomic():
        if new_items:
            TrackerItem.objects.bulk_create(new_items)

        tracker.end_date = new_end_date
        tracker.save(update_fields=["end_date", "updated_at"])

        if update_loan_due_date and tracker.loan:
            tracker.loan.due_date = new_end_date
            tracker.loan.save(update_fields=["due_date"])
            messages.success(
                request,
                f'Tracker "{tracker.title}" extended by {months_to_add} month(s) up to {new_end_date.strftime("%B %Y")}. '
                f'Loan #{str(tracker.loan.loan_id)[:8]} due date updated to {new_end_date.strftime("%d %b %Y")}.'
            )
        else:
            messages.success(
                request,
                f'Tracker "{tracker.title}" extended by {months_to_add} month(s) up to {new_end_date.strftime("%B %Y")}. '
                f'Loan due date remains unchanged.'
            )

    return redirect("lending:borrower_detail", pk=tracker.borrower.pk)


@login_required
@require_POST
def delete_tracker(request, tracker_id):
    tracker = get_object_or_404(
        BorrowerTracker,
        pk=tracker_id,
        borrower__lender=request.user,
    )
    borrower_id = tracker.borrower.pk
    tracker_title = tracker.title
    tracker.delete()
    messages.success(request, f'Tracker "{tracker_title}" was deleted.')
    return redirect("lending:borrower_detail", pk=borrower_id)


@login_required
@require_POST
def add_tracker_item(request, tracker_id):
    tracker = get_object_or_404(
        BorrowerTracker,
        pk=tracker_id,
        borrower__lender=request.user,
    )
    form = TrackerItemForm(request.POST)

    if form.is_valid():
        item = form.save(commit=False)
        item.tracker = tracker
        item.save()
        messages.success(request, f'Item "{item.title}" added to checklist.')
    else:
        messages.error(request, "Could not add checklist item. Title is required.")

    return redirect("lending:borrower_detail", pk=tracker.borrower.pk)


@login_required
@require_POST
def edit_tracker_item(request, item_id):
    item = get_object_or_404(
        TrackerItem,
        pk=item_id,
        tracker__borrower__lender=request.user,
    )
    form = TrackerItemForm(request.POST, instance=item)

    if form.is_valid():
        form.save()
        messages.success(request, f'Checklist item "{item.title}" updated.')
    else:
        messages.error(request, "Could not update checklist item. Title is required.")

    return redirect("lending:borrower_detail", pk=item.tracker.borrower.pk)


@login_required
@require_POST
def delete_tracker_item(request, item_id):
    item = get_object_or_404(
        TrackerItem,
        pk=item_id,
        tracker__borrower__lender=request.user,
    )
    borrower_id = item.tracker.borrower.pk
    item_title = item.title
    item.delete()
    messages.success(request, f'Checklist item "{item_title}" was deleted.')
    return redirect("lending:borrower_detail", pk=borrower_id)


@login_required
@require_POST
def toggle_tracker_item(request, item_id):
    item = get_object_or_404(
        TrackerItem,
        pk=item_id,
        tracker__borrower__lender=request.user,
    )

    item.is_completed = not item.is_completed
    item.completed_at = timezone.now() if item.is_completed else None
    item.save(update_fields=["is_completed", "completed_at", "updated_at"])

    # If AJAX requested, return JSON
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        tracker = item.tracker
        return JsonResponse({
            "success": True,
            "item_id": item.pk,
            "is_completed": item.is_completed,
            "completed_at": item.completed_at.strftime("%d %b %Y %H:%M") if item.completed_at else None,
            "total_items": tracker.total_items_count,
            "completed_items": tracker.completed_items_count,
            "pending_items": tracker.pending_items_count,
            "progress_percentage": tracker.progress_percentage,
        })

    status_str = "completed" if item.is_completed else "pending"
    messages.success(request, f'"{item.title}" marked as {status_str}.')
    return redirect("lending:borrower_detail", pk=item.tracker.borrower.pk)
