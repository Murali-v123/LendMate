from django.contrib import admin
from .models import Borrower, Loan, Payment, BorrowerTracker, TrackerItem


@admin.register(Borrower)
class BorrowerAdmin(admin.ModelAdmin):
    list_display = (
        "full_name",
        "mobile_number",
        "email",
        "lender",
        "whatsapp_consent",
        "sms_consent",
        "created_at",
    )

    search_fields = (
        "full_name",
        "mobile_number",
        "email",
    )

    list_filter = (
        "whatsapp_consent",
        "sms_consent",
        "created_at",
    )

    readonly_fields = (
        "lender",
        "created_at",
    )

    def get_queryset(self, request):
        queryset = super().get_queryset(request)

        if request.user.is_superuser:
            return queryset

        return queryset.filter(lender=request.user)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.lender = request.user

        super().save_model(request, obj, form, change)


@admin.register(Loan)
class LoanAdmin(admin.ModelAdmin):
    list_display = (
        "loan_id",
        "borrower",
        "principal",
        "interest_rate",
        "interest_period",
        "interest_basis",
        "lending_date",
        "due_date",
        "status",
        "closed_at",
    )

    search_fields = (
        "borrower__full_name",
        "loan_id",
    )

    list_filter = (
        "status",
        "interest_period",
        "interest_basis",
    )

    readonly_fields = (
        "loan_id",
        "created_at",
    )

    def get_queryset(self, request):
        queryset = super().get_queryset(request).select_related(
            "borrower",
            "borrower__lender",
        )

        if request.user.is_superuser:
            return queryset

        return queryset.filter(borrower__lender=request.user)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "borrower" and not request.user.is_superuser:
            kwargs["queryset"] = Borrower.objects.filter(
                lender=request.user
            )

        return super().formfield_for_foreignkey(
            db_field, request, **kwargs
        )


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "loan",
        "payment_date",
        "amount",
        "principal_component",
        "interest_component",
        "created_at",
    )


class TrackerItemInline(admin.TabularInline):
    model = TrackerItem
    extra = 1


@admin.register(BorrowerTracker)
class BorrowerTrackerAdmin(admin.ModelAdmin):
    list_display = ("title", "borrower", "tracker_type", "loan", "start_date", "end_date", "created_at")
    list_filter = ("tracker_type",)
    inlines = [TrackerItemInline]


@admin.register(TrackerItem)
class TrackerItemAdmin(admin.ModelAdmin):
    list_display = ("title", "tracker", "tracking_date", "is_completed", "completed_at")
    list_filter = ("is_completed",)
