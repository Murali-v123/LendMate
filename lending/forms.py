from django import forms

from .models import Borrower, Loan, Payment, BorrowerTracker, TrackerItem


class BorrowerForm(forms.ModelForm):
    class Meta:
        model = Borrower

        fields = [
            "full_name",
            "mobile_number",
            "email",
            "notes",
            "whatsapp_consent",
            "sms_consent",
        ]

        widgets = {
            "full_name": forms.TextInput(attrs={
                "placeholder": "Enter borrower's full name",
                "class": "form-control",
            }),
            "mobile_number": forms.TextInput(attrs={
                "placeholder": "Enter mobile number",
                "class": "form-control",
            }),
            "email": forms.EmailInput(attrs={
                "placeholder": "Email address (optional)",
                "class": "form-control",
            }),
            "notes": forms.Textarea(attrs={
                "placeholder": "Add any additional notes...",
                "class": "form-control",
                "rows": 4,
            }),
            "whatsapp_consent": forms.CheckboxInput(attrs={
                "class": "form-check-input",
            }),
            "sms_consent": forms.CheckboxInput(attrs={
                "class": "form-check-input",
            }),
        }

    def clean_sms_consent(self):
        """Preserve existing SMS consent when editing so it is not wiped when omitted from UI."""
        if "sms_consent" not in self.data and self.instance and self.instance.pk:
            return self.instance.sms_consent
        return self.cleaned_data.get("sms_consent", False)


class LoanForm(forms.ModelForm):
    class Meta:
        model = Loan

        fields = [
            "borrower",
            "principal",
            "interest_rate",
            "interest_period",
            "interest_basis",
            "lending_date",
            "due_date",
            "monthly_due_day",
            "notes",
        ]

        widgets = {
            "principal": forms.NumberInput(attrs={
                "class": "form-control",
                "placeholder": "Enter loan amount",
                "step": "0.01",
                "min": "0.01",
            }),
            "interest_rate": forms.NumberInput(attrs={
                "class": "form-control",
                "placeholder": "Enter interest rate",
                "step": "0.01",
                "min": "0",
            }),
            "interest_period": forms.Select(attrs={
                "class": "form-select",
            }),
            "interest_basis": forms.Select(attrs={
                "class": "form-select",
            }),
            "lending_date": forms.DateInput(attrs={
                "class": "form-control",
                "type": "date",
            }),
            "due_date": forms.DateInput(attrs={
                "class": "form-control",
                "type": "date",
            }),
            "monthly_due_day": forms.NumberInput(attrs={
                "class": "form-control",
                "placeholder": "Example: 5",
                "min": "1",
                "max": "31",
            }),
            "notes": forms.Textarea(attrs={
                "class": "form-control",
                "placeholder": "Additional loan notes...",
                "rows": 3,
            }),
        }

    def __init__(self, *args, lender=None, borrower=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["borrower"].queryset = Borrower.objects.filter(
            lender=lender
        )

        self.fields["borrower"].widget.attrs.update({
            "class": "form-select",
        })

        if borrower is not None:
            self.fields["borrower"].initial = borrower

    def clean(self):
        cleaned_data = super().clean()

        lending_date = cleaned_data.get("lending_date")
        due_date = cleaned_data.get("due_date")
        interest_period = cleaned_data.get("interest_period")
        monthly_due_day = cleaned_data.get("monthly_due_day")

        if lending_date and due_date and due_date < lending_date:
            self.add_error(
                "due_date",
                "Due date cannot be before the lending date."
            )

        if interest_period == "monthly" and monthly_due_day is None:
            self.add_error(
                "monthly_due_day",
                "Please enter the monthly interest due day."
            )

        return cleaned_data


class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment

        fields = [
            "loan",
            "payment_date",
            "amount",
            "principal_component",
            "interest_component",
            "notes",
        ]

        widgets = {
            "loan": forms.Select(attrs={
                "class": "form-select",
            }),
            "payment_date": forms.DateInput(attrs={
                "class": "form-control",
                "type": "date",
            }),
            "amount": forms.NumberInput(attrs={
                "class": "form-control",
                "placeholder": "Total payment amount",
                "step": "0.01",
                "min": "0.01",
            }),
            "principal_component": forms.NumberInput(attrs={
                "class": "form-control",
                "placeholder": "Amount towards principal",
                "step": "0.01",
                "min": "0",
            }),
            "interest_component": forms.NumberInput(attrs={
                "class": "form-control",
                "placeholder": "Amount towards interest",
                "step": "0.01",
                "min": "0",
            }),
            "notes": forms.Textarea(attrs={
                "class": "form-control",
                "placeholder": "Optional payment notes...",
                "rows": 3,
            }),
        }

    def __init__(self, *args, lender=None, loan=None, **kwargs):
        super().__init__(*args, **kwargs)

        # Only show loans belonging to the logged-in lender.
        self.fields["loan"].queryset = Loan.objects.filter(
            borrower__lender=lender,
            status="open",
        ).select_related("borrower")

        # If opened from a particular loan, preselect it.
        if loan is not None:
            self.fields["loan"].queryset = self.fields["loan"].queryset.filter(
                pk=loan.pk
            )
            self.fields["loan"].initial = loan

    def clean(self):
        cleaned_data = super().clean()

        amount = cleaned_data.get("amount")
        principal = cleaned_data.get("principal_component")
        interest = cleaned_data.get("interest_component")

        if (
            amount is not None
            and principal is not None
            and interest is not None
            and principal + interest != amount
        ):
            raise forms.ValidationError(
                "Principal amount and interest amount must equal the total payment."
            )

        return cleaned_data


class BorrowerTrackerForm(forms.ModelForm):
    class Meta:
        model = BorrowerTracker
        fields = ["title", "description"]
        widgets = {
            "title": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "e.g. Monthly Interest Collection, Document Follow-up...",
                "required": True,
            }),
            "description": forms.Textarea(attrs={
                "class": "form-control",
                "placeholder": "Optional description or context...",
                "rows": 2,
            }),
        }


class TrackerItemForm(forms.ModelForm):
    class Meta:
        model = TrackerItem
        fields = ["title", "notes"]
        widgets = {
            "title": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Checklist item title...",
                "required": True,
            }),
            "notes": forms.Textarea(attrs={
                "class": "form-control",
                "placeholder": "Optional notes or details...",
                "rows": 2,
            }),
        }


class AutomaticTrackerForm(forms.Form):
    loan = forms.ModelChoiceField(
        queryset=Loan.objects.none(),
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Select Loan",
        empty_label="Choose a loan...",
    )
    title = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Optional tracker title (defaults to Monthly Loan Tracker)",
        }),
        label="Tracker Title (Optional)",
    )
    description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            "class": "form-control",
            "placeholder": "Optional description...",
            "rows": 2,
        }),
        label="Description (Optional)",
    )

    def __init__(self, *args, borrower=None, lender=None, **kwargs):
        super().__init__(*args, **kwargs)
        if borrower is not None:
            self.fields["loan"].queryset = Loan.objects.filter(
                borrower=borrower,
                borrower__lender=lender,
            ).order_by("-created_at")

    def clean_loan(self):
        loan = self.cleaned_data.get("loan")
        if not loan:
            raise forms.ValidationError("Please select a loan.")
        if not loan.due_date:
            raise forms.ValidationError(
                "This loan does not have an expected return date (due date). "
                "Please set an expected return date on the loan before generating an automatic monthly tracker."
            )
        return loan


class ExtendTrackerForm(forms.Form):
    EXTENSION_CHOICES = [
        ("1", "Extend by 1 Month"),
        ("2", "Extend by 2 Months"),
        ("3", "Extend by 3 Months"),
        ("6", "Extend by 6 Months"),
        ("custom", "Custom Number of Months"),
    ]

    extension_preset = forms.ChoiceField(
        choices=EXTENSION_CHOICES,
        initial="1",
        widget=forms.Select(attrs={"class": "form-select", "id": "extensionPreset"}),
        label="Extension Duration",
    )
    custom_months = forms.IntegerField(
        required=False,
        min_value=1,
        max_value=120,
        widget=forms.NumberInput(attrs={
            "class": "form-control",
            "placeholder": "Enter number of months...",
            "min": "1",
            "id": "customMonthsInput",
        }),
        label="Custom Months",
    )
    update_loan_due_date = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        label="Also update the loan's expected return date (due date) to match the new tracker end date",
    )

    def clean(self):
        cleaned_data = super().clean()
        preset = cleaned_data.get("extension_preset")
        custom_months = cleaned_data.get("custom_months")

        if preset == "custom":
            if not custom_months or custom_months < 1:
                self.add_error("custom_months", "Please enter a valid number of months (minimum 1).")
        return cleaned_data

    def get_months_to_add(self):
        preset = self.cleaned_data.get("extension_preset")
        if preset == "custom":
            return self.cleaned_data.get("custom_months") or 1
        return int(preset)
