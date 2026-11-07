import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models import Sum


class Borrower(models.Model):
    lender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="borrowers",
        null=True,
        blank=True,
    )

    full_name = models.CharField(max_length=150)
    mobile_number = models.CharField(max_length=15)
    email = models.EmailField(blank=True, null=True)
    notes = models.TextField(blank=True)
    whatsapp_consent = models.BooleanField(
        default=False,
        help_text="Consent to receive WhatsApp notifications."
    )
    sms_consent = models.BooleanField(
        default=False,
        help_text="Consent to receive SMS notifications (deprecated)."
    )
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def total_borrowed(self):
        return self.loans.aggregate(
            total=Sum("principal")
        )["total"] or Decimal("0.00")

    @property
    def outstanding_principal(self):
        total = Decimal("0.00")
        for loan in self.loans.all():
            total += loan.outstanding_principal
        return total

    @property
    def active_loans_count(self):
        return self.loans.filter(status="open").count()

    @property
    def closed_loans_count(self):
        return self.loans.filter(status="closed").count()

    @property
    def total_loans_count(self):
        return self.loans.count()

    @property
    def is_active_status(self):
        return self.active_loans_count > 0

    @property
    def sms_notifications(self):
        """Deprecated backward-compatibility accessor."""
        return self.notifications.all()

    def __str__(self):
        return self.full_name


class Loan(models.Model):
    INTEREST_PERIOD_CHOICES = [
        ("monthly", "Monthly"),
        ("annually", "Annually"),
    ]

    INTEREST_BASIS_CHOICES = [
        ("original", "Original Principal"),
        ("reducing", "Reducing Balance"),
    ]

    STATUS_CHOICES = [
        ("open", "Open"),
        ("closed", "Closed"),
    ]

    loan_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    borrower = models.ForeignKey(
        Borrower, on_delete=models.PROTECT, related_name="loans"
    )

    principal = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0.01)],
    )

    interest_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )

    interest_period = models.CharField(
        max_length=10,
        choices=INTEREST_PERIOD_CHOICES,
    )

    interest_basis = models.CharField(
        max_length=10,
        choices=INTEREST_BASIS_CHOICES,
    )

    lending_date = models.DateField()
    due_date = models.DateField(null=True, blank=True)

    monthly_due_day = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[
            MinValueValidator(1),
            MaxValueValidator(31),
        ],
    )

    notes = models.TextField(blank=True)

    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default="open",
    )

    closed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def principal_repaid(self):
        return self.payments.aggregate(
            total=Sum("principal_component")
        )["total"] or Decimal("0.00")

    @property
    def outstanding_principal(self):
        return self.principal - self.principal_repaid

    @property
    def sms_notifications(self):
        """Deprecated backward-compatibility accessor."""
        return self.notifications.all()

    def __str__(self):
        return f"Loan - {self.borrower.full_name}"


class Payment(models.Model):
    loan = models.ForeignKey(
        Loan,
        on_delete=models.PROTECT,
        related_name="payments",
    )

    payment_date = models.DateField()

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0.01)],
    )

    principal_component = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(0)],
    )

    interest_component = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(0)],
    )

    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        super().clean()

        if self.amount is None:
            return

        if (
            self.principal_component is None
            or self.interest_component is None
        ):
            return

        if (
            self.principal_component + self.interest_component
            != self.amount
        ):
            raise ValidationError(
                "Principal and interest components must equal the total payment."
            )

        if self.loan_id:
            previous_paid = Payment.objects.filter(
                loan_id=self.loan_id
            ).exclude(pk=self.pk).aggregate(
                total=Sum("principal_component")
            )["total"] or Decimal("0.00")

            if previous_paid + self.principal_component > self.loan.principal:
                raise ValidationError(
                    "Principal payment cannot exceed the outstanding principal."
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Payment - {self.loan.loan_id} - ₹{self.amount}"

    @property
    def sms_notifications(self):
        """Deprecated backward-compatibility accessor."""
        return self.notifications.all()


class BorrowerTracker(models.Model):
    TRACKER_TYPE_CHOICES = [
        ("custom", "Custom Tracker"),
        ("automatic", "Automatic Monthly Tracker"),
    ]

    borrower = models.ForeignKey(
        Borrower,
        on_delete=models.CASCADE,
        related_name="trackers",
    )
    tracker_type = models.CharField(
        max_length=20,
        choices=TRACKER_TYPE_CHOICES,
        default="custom",
    )
    loan = models.ForeignKey(
        Loan,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="trackers",
    )
    title = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} - {self.borrower.full_name}"

    @property
    def is_automatic(self):
        return self.tracker_type == "automatic"

    @property
    def is_custom(self):
        return self.tracker_type == "custom"

    @property
    def total_items_count(self):
        return self.items.count()

    @property
    def completed_items_count(self):
        return self.items.filter(is_completed=True).count()

    @property
    def pending_items_count(self):
        return self.items.filter(is_completed=False).count()

    @property
    def progress_percentage(self):
        total = self.total_items_count
        if total == 0:
            return 0
        return int(round((self.completed_items_count / total) * 100))


class TrackerItem(models.Model):
    tracker = models.ForeignKey(
        BorrowerTracker,
        on_delete=models.CASCADE,
        related_name="items",
    )
    title = models.CharField(max_length=200)
    notes = models.TextField(blank=True)
    tracking_date = models.DateField(null=True, blank=True)
    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return self.title
