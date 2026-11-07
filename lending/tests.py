import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Borrower, Loan, Payment, BorrowerTracker, TrackerItem


class LendingBaseTestCase(TestCase):
    def setUp(self):
        self.lender = User.objects.create_user(
            username="testlender",
            email="lender@example.com",
            password="SecurePassword123!",
            first_name="Jane",
            last_name="Doe",
        )
        self.other_lender = User.objects.create_user(
            username="otherlender",
            email="other@example.com",
            password="SecurePassword123!",
            first_name="John",
            last_name="Smith",
        )

        self.borrower = Borrower.objects.create(
            lender=self.lender,
            full_name="Alice Johnson",
            mobile_number="9876543210",
            email="alice@example.com",
            notes="Reliable borrower",
            sms_consent=True,
        )

        self.other_borrower = Borrower.objects.create(
            lender=self.other_lender,
            full_name="Bob Miller",
            mobile_number="9123456789",
            email="bob@example.com",
        )

        self.loan_1 = Loan.objects.create(
            borrower=self.borrower,
            principal=Decimal("10000.00"),
            interest_rate=Decimal("12.00"),
            interest_period="monthly",
            interest_basis="original",
            lending_date=datetime.date(2026, 1, 1),
            due_date=datetime.date(2026, 12, 31),
            monthly_due_day=5,
            status="open",
        )

        self.loan_2 = Loan.objects.create(
            borrower=self.borrower,
            principal=Decimal("5000.00"),
            interest_rate=Decimal("10.00"),
            interest_period="monthly",
            interest_basis="reducing",
            lending_date=datetime.date(2026, 2, 1),
            monthly_due_day=10,
            status="open",
        )

        self.payment_1 = Payment.objects.create(
            loan=self.loan_1,
            payment_date=datetime.date(2026, 2, 5),
            amount=Decimal("1100.00"),
            principal_component=Decimal("1000.00"),
            interest_component=Decimal("100.00"),
            notes="First month installment",
        )


class BorrowerManagementTests(LendingBaseTestCase):
    def test_borrower_list_requires_login(self):
        response = self.client.get(reverse("lending:borrower_list"))
        self.assertEqual(response.status_code, 302)

    def test_borrower_list_shows_only_lenders_borrowers(self):
        self.client.force_login(self.lender)
        response = self.client.get(reverse("lending:borrower_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alice Johnson")
        self.assertNotContains(response, "Bob Miller")

    def test_borrower_search_by_name(self):
        self.client.force_login(self.lender)
        response = self.client.get(reverse("lending:borrower_list") + "?q=Alice")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alice Johnson")

        response_nomatch = self.client.get(reverse("lending:borrower_list") + "?q=NonExistent")
        self.assertNotContains(response_nomatch, "Alice Johnson")
        self.assertContains(response_nomatch, "No matching borrowers found")

    def test_borrower_search_by_mobile(self):
        self.client.force_login(self.lender)
        response = self.client.get(reverse("lending:borrower_list") + "?q=9876543210")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alice Johnson")

    def test_borrower_filter_by_status(self):
        self.client.force_login(self.lender)

        # Borrower with open loans is active
        response = self.client.get(reverse("lending:borrower_list") + "?status=active")
        self.assertContains(response, "Alice Johnson")

        # Inactive filter should exclude Alice
        response_inactive = self.client.get(reverse("lending:borrower_list") + "?status=inactive")
        self.assertNotContains(response_inactive, "Alice Johnson")

    def test_add_borrower(self):
        self.client.force_login(self.lender)
        response = self.client.post(
            reverse("lending:add_borrower"),
            {
                "full_name": "Charlie Brown",
                "mobile_number": "9998887776",
                "email": "charlie@example.com",
                "notes": "Friend from college",
                "whatsapp_consent": True,
                "sms_consent": True,
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        charlie = Borrower.objects.filter(full_name="Charlie Brown", lender=self.lender).first()
        self.assertIsNotNone(charlie)
        self.assertTrue(charlie.whatsapp_consent)

    def test_edit_borrower(self):
        self.client.force_login(self.lender)
        response = self.client.post(
            reverse("lending:edit_borrower", kwargs={"pk": self.borrower.pk}),
            {
                "full_name": "Alice Johnson Updated",
                "mobile_number": "9876543210",
                "email": "alice.new@example.com",
                "notes": "Updated note",
                "whatsapp_consent": True,
                "sms_consent": False,
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.borrower.refresh_from_db()
        self.assertEqual(self.borrower.full_name, "Alice Johnson Updated")
        self.assertEqual(self.borrower.email, "alice.new@example.com")
        self.assertTrue(self.borrower.whatsapp_consent)
        self.assertFalse(self.borrower.sms_consent)

    def test_edit_borrower_preserves_sms_consent_when_omitted(self):
        """
        Editing a borrower when the UI form only submits WhatsApp consent
        must NOT accidentally wipe out existing historical sms_consent.
        """
        self.client.force_login(self.lender)
        self.borrower.sms_consent = True
        self.borrower.whatsapp_consent = False
        self.borrower.save()

        # Submit form omitting 'sms_consent' entirely
        response = self.client.post(
            reverse("lending:edit_borrower", kwargs={"pk": self.borrower.pk}),
            {
                "full_name": "Alice Johnson",
                "mobile_number": "9876543210",
                "email": "alice@example.com",
                "notes": "Updated notes",
                "whatsapp_consent": True,
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.borrower.refresh_from_db()
        self.assertTrue(self.borrower.whatsapp_consent)
        # sms_consent must remain True (not wiped out to False)
        self.assertTrue(self.borrower.sms_consent)

    def test_borrower_detail_page_loads(self):
        self.client.force_login(self.lender)
        response = self.client.get(reverse("lending:borrower_detail", kwargs={"pk": self.borrower.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alice Johnson")
        self.assertContains(response, "10000.00")
        self.assertContains(response, "5000.00")
        self.assertContains(response, "First month installment")
        self.assertContains(response, "Custom and Automatic Trackers")


class CustomTrackerTests(LendingBaseTestCase):
    def test_create_tracker(self):
        self.client.force_login(self.lender)
        response = self.client.post(
            reverse("lending:create_tracker", kwargs={"borrower_id": self.borrower.pk}),
            {
                "title": "Monthly Interest Collection",
                "description": "Track interest payment dates for 2026",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            BorrowerTracker.objects.filter(
                borrower=self.borrower, title="Monthly Interest Collection"
            ).exists()
        )

    def test_tracker_item_workflow_and_progress(self):
        self.client.force_login(self.lender)
        tracker = BorrowerTracker.objects.create(
            borrower=self.borrower,
            title="Document Collection",
        )

        # Add 2 items
        self.client.post(
            reverse("lending:add_tracker_item", kwargs={"tracker_id": tracker.pk}),
            {"title": "Collect PAN Card", "notes": "Identity check"},
            follow=True,
        )
        self.client.post(
            reverse("lending:add_tracker_item", kwargs={"tracker_id": tracker.pk}),
            {"title": "Collect Promissory Note", "notes": "Signed agreement"},
            follow=True,
        )

        self.assertEqual(tracker.total_items_count, 2)
        self.assertEqual(tracker.completed_items_count, 0)
        self.assertEqual(tracker.progress_percentage, 0)

        item1 = tracker.items.first()
        item2 = tracker.items.last()

        # Toggle item 1 as completed
        self.client.post(
            reverse("lending:toggle_tracker_item", kwargs={"item_id": item1.pk}),
            follow=True,
        )
        item1.refresh_from_db()
        self.assertTrue(item1.is_completed)
        self.assertIsNotNone(item1.completed_at)
        self.assertEqual(tracker.completed_items_count, 1)
        self.assertEqual(tracker.progress_percentage, 50)

        # Untick item 1
        self.client.post(
            reverse("lending:toggle_tracker_item", kwargs={"item_id": item1.pk}),
            follow=True,
        )
        item1.refresh_from_db()
        self.assertFalse(item1.is_completed)
        self.assertIsNone(item1.completed_at)
        self.assertEqual(tracker.progress_percentage, 0)

        # Edit item 2
        self.client.post(
            reverse("lending:edit_tracker_item", kwargs={"item_id": item2.pk}),
            {"title": "Collect Signed Promissory Note", "notes": "Urgent"},
            follow=True,
        )
        item2.refresh_from_db()
        self.assertEqual(item2.title, "Collect Signed Promissory Note")

        # Delete item 1 without affecting loan records
        self.client.post(
            reverse("lending:delete_tracker_item", kwargs={"item_id": item1.pk}),
            follow=True,
        )
        self.assertEqual(tracker.items.count(), 1)
        # Verify loan records and payments remain intact
        self.assertEqual(Loan.objects.filter(borrower=self.borrower).count(), 2)
        self.assertEqual(Payment.objects.filter(loan=self.loan_1).count(), 1)


class LoanClosureTests(LendingBaseTestCase):
    def test_close_loan(self):
        self.client.force_login(self.lender)
        response = self.client.post(
            reverse("lending:close_loan", kwargs={"loan_id": self.loan_1.loan_id}),
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.loan_1.refresh_from_db()
        self.assertEqual(self.loan_1.status, "closed")
        self.assertIsNotNone(self.loan_1.closed_at)

        # Closing loan 1 does NOT close loan 2
        self.loan_2.refresh_from_db()
        self.assertEqual(self.loan_2.status, "open")

        # Payments remain intact
        self.assertEqual(self.loan_1.payments.count(), 1)
        self.assertEqual(self.loan_1.outstanding_principal, Decimal("9000.00"))

    def test_reopen_loan(self):
        self.client.force_login(self.lender)
        self.loan_1.status = "closed"
        self.loan_1.closed_at = datetime.datetime.now(datetime.timezone.utc)
        self.loan_1.save()

        response = self.client.post(
            reverse("lending:reopen_loan", kwargs={"loan_id": self.loan_1.loan_id}),
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.loan_1.refresh_from_db()
        self.assertEqual(self.loan_1.status, "open")
        self.assertIsNone(self.loan_1.closed_at)


class SecurityAndIsolationTests(LendingBaseTestCase):
    def test_other_lender_cannot_access_borrower_detail(self):
        self.client.force_login(self.other_lender)
        response = self.client.get(
            reverse("lending:borrower_detail", kwargs={"pk": self.borrower.pk})
        )
        self.assertEqual(response.status_code, 404)

    def test_other_lender_cannot_edit_borrower(self):
        self.client.force_login(self.other_lender)
        response = self.client.post(
            reverse("lending:edit_borrower", kwargs={"pk": self.borrower.pk}),
            {"full_name": "Hijacked Name", "mobile_number": "1234567890"},
        )
        self.assertEqual(response.status_code, 404)
        self.borrower.refresh_from_db()
        self.assertEqual(self.borrower.full_name, "Alice Johnson")

    def test_other_lender_cannot_close_loan(self):
        self.client.force_login(self.other_lender)
        response = self.client.post(
            reverse("lending:close_loan", kwargs={"loan_id": self.loan_1.loan_id})
        )
        self.assertEqual(response.status_code, 404)
        self.loan_1.refresh_from_db()
        self.assertEqual(self.loan_1.status, "open")

    def test_other_lender_cannot_create_or_delete_tracker(self):
        self.client.force_login(self.other_lender)
        response = self.client.post(
            reverse("lending:create_tracker", kwargs={"borrower_id": self.borrower.pk}),
            {"title": "Unauthorized Tracker"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(BorrowerTracker.objects.filter(title="Unauthorized Tracker").exists())


class DashboardImprovementTests(LendingBaseTestCase):
    def test_dashboard_renders_all_required_metrics(self):
        self.client.force_login(self.lender)
        response = self.client.get(reverse("core:dashboard"))
        self.assertEqual(response.status_code, 200)

        context = response.context
        self.assertEqual(context["total_borrowers"], 1)
        self.assertEqual(context["active_borrowers"], 1)
        self.assertEqual(context["total_loans"], 2)
        self.assertEqual(context["active_loans"], 2)
        self.assertEqual(context["closed_loans"], 0)
        self.assertEqual(context["total_lent"], Decimal("15000.00"))
        self.assertEqual(context["outstanding"], Decimal("14000.00"))
        self.assertEqual(context["interest_received"], Decimal("100.00"))

        # Verify Quick Actions present
        self.assertContains(response, reverse("lending:add_borrower"))
        self.assertContains(response, reverse("lending:add_loan"))
        self.assertContains(response, reverse("lending:add_payment"))
        self.assertContains(response, reverse("lending:borrower_list"))


class AutomaticMonthlyTrackerTests(LendingBaseTestCase):
    def setUp(self):
        super().setUp()
        # Create a loan from Nov 5, 2026 to Nov 5, 2027
        self.annual_loan = Loan.objects.create(
            borrower=self.borrower,
            principal=Decimal("20000.00"),
            interest_rate=Decimal("12.00"),
            interest_period="monthly",
            interest_basis="original",
            lending_date=datetime.date(2026, 11, 5),
            due_date=datetime.date(2027, 11, 5),
            status="open",
        )

        # Loan without due date
        self.loan_no_due = Loan.objects.create(
            borrower=self.borrower,
            principal=Decimal("8000.00"),
            interest_rate=Decimal("10.00"),
            interest_period="monthly",
            interest_basis="original",
            lending_date=datetime.date(2026, 5, 1),
            due_date=None,
            status="open",
        )

    def test_create_automatic_monthly_tracker_generates_correct_sequence(self):
        self.client.force_login(self.lender)
        response = self.client.post(
            reverse("lending:create_automatic_tracker", kwargs={"borrower_id": self.borrower.pk}),
            {"loan": self.annual_loan.pk},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)

        tracker = BorrowerTracker.objects.get(loan=self.annual_loan, tracker_type="automatic")
        self.assertTrue(tracker.is_automatic)
        self.assertEqual(tracker.start_date, datetime.date(2026, 11, 5))
        self.assertEqual(tracker.end_date, datetime.date(2027, 11, 5))

        # Nov 2026 to Nov 2027 inclusive = 13 months
        items = tracker.items.order_by("created_at")
        self.assertEqual(items.count(), 13)
        self.assertEqual(items.first().title, "November 2026")
        self.assertEqual(items.last().title, "November 2027")

    def test_cannot_create_automatic_tracker_for_loan_without_due_date(self):
        self.client.force_login(self.lender)
        response = self.client.post(
            reverse("lending:create_automatic_tracker", kwargs={"borrower_id": self.borrower.pk}),
            {"loan": self.loan_no_due.pk},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            BorrowerTracker.objects.filter(loan=self.loan_no_due, tracker_type="automatic").exists()
        )
        self.assertContains(response, "This loan does not have an expected return date")

    def test_prevent_duplicate_automatic_tracker_for_same_loan(self):
        self.client.force_login(self.lender)
        # Create first
        self.client.post(
            reverse("lending:create_automatic_tracker", kwargs={"borrower_id": self.borrower.pk}),
            {"loan": self.annual_loan.pk},
            follow=True,
        )
        self.assertEqual(
            BorrowerTracker.objects.filter(loan=self.annual_loan, tracker_type="automatic").count(), 1
        )

        # Attempt to create duplicate
        response = self.client.post(
            reverse("lending:create_automatic_tracker", kwargs={"borrower_id": self.borrower.pk}),
            {"loan": self.annual_loan.pk},
            follow=True,
        )
        self.assertEqual(
            BorrowerTracker.objects.filter(loan=self.annual_loan, tracker_type="automatic").count(), 1
        )
        self.assertContains(response, "An automatic monthly tracker already exists")

    def test_tick_untick_and_notes_on_monthly_tracker(self):
        self.client.force_login(self.lender)
        self.client.post(
            reverse("lending:create_automatic_tracker", kwargs={"borrower_id": self.borrower.pk}),
            {"loan": self.annual_loan.pk},
            follow=True,
        )
        tracker = BorrowerTracker.objects.get(loan=self.annual_loan)
        first_item = tracker.items.first()

        # Tick
        self.client.post(
            reverse("lending:toggle_tracker_item", kwargs={"item_id": first_item.pk}),
            follow=True,
        )
        first_item.refresh_from_db()
        self.assertTrue(first_item.is_completed)
        self.assertIsNotNone(first_item.completed_at)

        # Edit notes
        self.client.post(
            reverse("lending:edit_tracker_item", kwargs={"item_id": first_item.pk}),
            {"title": first_item.title, "notes": "Received ₹200 via UPI"},
            follow=True,
        )
        first_item.refresh_from_db()
        self.assertEqual(first_item.notes, "Received ₹200 via UPI")

        # Untick
        self.client.post(
            reverse("lending:toggle_tracker_item", kwargs={"item_id": first_item.pk}),
            follow=True,
        )
        first_item.refresh_from_db()
        self.assertFalse(first_item.is_completed)
        self.assertIsNone(first_item.completed_at)
        # Notes remain preserved
        self.assertEqual(first_item.notes, "Received ₹200 via UPI")

    def test_extend_automatic_tracker_preserves_completed_and_adds_months(self):
        self.client.force_login(self.lender)
        self.client.post(
            reverse("lending:create_automatic_tracker", kwargs={"borrower_id": self.borrower.pk}),
            {"loan": self.annual_loan.pk},
            follow=True,
        )
        tracker = BorrowerTracker.objects.get(loan=self.annual_loan)
        first_item = tracker.items.first()

        # Mark first item as completed with notes
        first_item.is_completed = True
        first_item.completed_at = datetime.datetime.now(datetime.timezone.utc)
        first_item.notes = "Early settlement"
        first_item.save()

        # Extend by 3 months (Nov 2027 -> Feb 2028)
        self.client.post(
            reverse("lending:extend_tracker", kwargs={"tracker_id": tracker.pk}),
            {
                "extension_preset": "3",
            },
            follow=True,
        )
        tracker.refresh_from_db()
        self.assertEqual(tracker.end_date, datetime.date(2028, 2, 5))

        # 13 original + 3 extended = 16 months
        items = tracker.items.order_by("created_at")
        self.assertEqual(items.count(), 16)
        titles = [i.title for i in items]
        self.assertIn("December 2027", titles)
        self.assertIn("January 2028", titles)
        self.assertIn("February 2028", titles)

        # Check first item was preserved
        first_item.refresh_from_db()
        self.assertTrue(first_item.is_completed)
        self.assertEqual(first_item.notes, "Early settlement")

        # Loan due date remained unchanged because update_loan_due_date was not checked
        self.annual_loan.refresh_from_db()
        self.assertEqual(self.annual_loan.due_date, datetime.date(2027, 11, 5))

    def test_extend_with_explicit_loan_due_date_update(self):
        self.client.force_login(self.lender)
        self.client.post(
            reverse("lending:create_automatic_tracker", kwargs={"borrower_id": self.borrower.pk}),
            {"loan": self.annual_loan.pk},
            follow=True,
        )
        tracker = BorrowerTracker.objects.get(loan=self.annual_loan)

        # Extend by 2 months and also update loan due date
        self.client.post(
            reverse("lending:extend_tracker", kwargs={"tracker_id": tracker.pk}),
            {
                "extension_preset": "2",
                "update_loan_due_date": "on",
            },
            follow=True,
        )
        self.annual_loan.refresh_from_db()
        self.assertEqual(self.annual_loan.due_date, datetime.date(2028, 1, 5))

    def test_custom_extension_duration_and_repeated_extensions(self):
        self.client.force_login(self.lender)
        self.client.post(
            reverse("lending:create_automatic_tracker", kwargs={"borrower_id": self.borrower.pk}),
            {"loan": self.annual_loan.pk},
            follow=True,
        )
        tracker = BorrowerTracker.objects.get(loan=self.annual_loan)

        # Custom extension by 1 month
        self.client.post(
            reverse("lending:extend_tracker", kwargs={"tracker_id": tracker.pk}),
            {
                "extension_preset": "custom",
                "custom_months": 1,
            },
            follow=True,
        )
        tracker.refresh_from_db()
        self.assertEqual(tracker.items.count(), 14)

        # Extend again by 2 months
        self.client.post(
            reverse("lending:extend_tracker", kwargs={"tracker_id": tracker.pk}),
            {
                "extension_preset": "2",
            },
            follow=True,
        )
        tracker.refresh_from_db()
        self.assertEqual(tracker.items.count(), 16)

        # Verify no duplicate titles
        titles = list(tracker.items.values_list("title", flat=True))
        self.assertEqual(len(titles), len(set(titles)))

    def test_closed_loan_tracker_can_be_extended(self):
        self.client.force_login(self.lender)
        self.annual_loan.status = "closed"
        self.annual_loan.save()

        # Create tracker for closed loan
        self.client.post(
            reverse("lending:create_automatic_tracker", kwargs={"borrower_id": self.borrower.pk}),
            {"loan": self.annual_loan.pk},
            follow=True,
        )
        tracker = BorrowerTracker.objects.get(loan=self.annual_loan)
        self.assertEqual(tracker.items.count(), 13)

        # Extend tracker
        response = self.client.post(
            reverse("lending:extend_tracker", kwargs={"tracker_id": tracker.pk}),
            {"extension_preset": "1"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        tracker.refresh_from_db()
        self.assertEqual(tracker.items.count(), 14)

        # Loan remains closed
        self.annual_loan.refresh_from_db()
        self.assertEqual(self.annual_loan.status, "closed")

    def test_security_cannot_create_or_extend_other_lenders_tracker(self):
        self.client.force_login(self.other_lender)
        # Try to create automatic tracker for self.borrower (owned by self.lender)
        response = self.client.post(
            reverse("lending:create_automatic_tracker", kwargs={"borrower_id": self.borrower.pk}),
            {"loan": self.annual_loan.pk},
        )
        self.assertEqual(response.status_code, 404)

        # Create a tracker as owner
        tracker = BorrowerTracker.objects.create(
            borrower=self.borrower,
            loan=self.annual_loan,
            tracker_type="automatic",
            title="Alice Annual Tracker",
            start_date=self.annual_loan.lending_date,
            end_date=self.annual_loan.due_date,
        )

        # Other lender tries to extend it
        response_extend = self.client.post(
            reverse("lending:extend_tracker", kwargs={"tracker_id": tracker.pk}),
            {"extension_preset": "1"},
        )
        self.assertEqual(response_extend.status_code, 404)

