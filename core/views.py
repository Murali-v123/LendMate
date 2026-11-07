
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import render, redirect

from lending.models import Borrower, Loan, Payment
from .forms import ProfileForm, UserPreferencesForm
from .models import UserPreferences


@login_required
def dashboard(request):
    # Get only the logged-in lender's records
    borrowers = Borrower.objects.filter(lender=request.user)

    loans = Loan.objects.filter(
        borrower__lender=request.user
    )

    payments = Payment.objects.filter(
        loan__borrower__lender=request.user
    )

    # Calculate total amount lent
    total_lent = loans.aggregate(
        total=Sum("principal")
    )["total"] or Decimal("0.00")

    # Calculate principal already repaid
    principal_paid = payments.aggregate(
        total=Sum("principal_component")
    )["total"] or Decimal("0.00")

    # Calculate outstanding principal
    outstanding = total_lent - principal_paid

    # Calculate interest received
    interest_received = payments.aggregate(
        total=Sum("interest_component")
    )["total"] or Decimal("0.00")

    # Count borrowers and loans
    total_borrowers = borrowers.count()
    active_borrowers = borrowers.filter(loans__status="open").distinct().count()
    total_loans = loans.count()
    active_loans = loans.filter(status="open").count()
    closed_loans = loans.filter(status="closed").count()

    # Get latest payments
    recent_payments = payments.select_related(
        "loan", "loan__borrower"
    ).order_by("-payment_date", "-created_at")[:5]

    context = {
        "total_lent": total_lent,
        "outstanding": outstanding,
        "interest_received": interest_received,
        "total_borrowers": total_borrowers,
        "active_borrowers": active_borrowers,
        "total_loans": total_loans,
        "active_loans": active_loans,
        "closed_loans": closed_loans,
        "recent_payments": recent_payments,
    }

    return render(request, "core/dashboard.html", context)


@login_required
def settings_view(request):
    preferences, _ = UserPreferences.objects.get_or_create(
        user=request.user
    )

    profile_form = ProfileForm(instance=request.user)
    preferences_form = UserPreferencesForm(instance=preferences)

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "profile":
            profile_form = ProfileForm(
                request.POST,
                instance=request.user
            )
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, "Profile updated successfully.")
                return redirect("core:settings")

        elif action == "preferences":
            preferences_form = UserPreferencesForm(
                request.POST,
                instance=preferences
            )
            if preferences_form.is_valid():
                preferences_form.save()
                messages.success(
                    request,
                    "Notification preferences updated successfully."
                )
                return redirect("core:settings")
        else:
            return redirect("core:settings")

    context = {
        "profile_form": profile_form,
        "preferences_form": preferences_form,
    }

    return render(request, "core/settings.html", context)
