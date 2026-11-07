from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse

from core.models import UserPreferences


class SettingsViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testlender",
            email="testlender@example.com",
            password="SecurePassword123!",
            first_name="Jane",
            last_name="Doe",
        )
        self.settings_url = reverse("core:settings")

    def test_login_required(self):
        response = self.client.get(self.settings_url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_settings_page_loads_for_authenticated_user(self):
        self.client.force_login(self.user)
        response = self.client.get(self.settings_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "core/settings.html")
        self.assertContains(response, "Lender profile")
        self.assertContains(response, "Notification preferences")
        self.assertContains(response, "Security")
        self.assertContains(response, reverse("accounts:password_change"))
        self.assertContains(response, "Save Profile")
        self.assertContains(response, "Save Preferences")
        self.assertContains(response, self.user.username)

    def test_preferences_auto_created_on_settings_visit(self):
        self.assertFalse(UserPreferences.objects.filter(user=self.user).exists())
        self.client.force_login(self.user)
        response = self.client.get(self.settings_url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(UserPreferences.objects.filter(user=self.user).exists())
        prefs = UserPreferences.objects.get(user=self.user)
        self.assertTrue(prefs.payment_reminders)
        self.assertTrue(prefs.due_date_reminders)

    def test_update_profile_success(self):
        self.client.force_login(self.user)
        response = self.client.post(
            self.settings_url,
            {
                "action": "profile",
                "first_name": "Janet",
                "last_name": "Smith",
                "email": "janet.smith@example.com",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Janet")
        self.assertEqual(self.user.last_name, "Smith")
        self.assertEqual(self.user.email, "janet.smith@example.com")
        messages = [m.message for m in get_messages(response.wsgi_request)]
        self.assertIn("Profile updated successfully.", messages)

    def test_username_cannot_be_changed_via_profile_form(self):
        self.client.force_login(self.user)
        self.client.post(
            self.settings_url,
            {
                "action": "profile",
                "username": "hackedusername",
                "first_name": "Hacker",
                "last_name": "Person",
                "email": "hacker@example.com",
            },
            follow=True,
        )
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "testlender")
        self.assertEqual(self.user.first_name, "Hacker")

    def test_invalid_profile_submission_shows_errors_without_redirect(self):
        self.client.force_login(self.user)
        response = self.client.post(
            self.settings_url,
            {
                "action": "profile",
                "first_name": "Janet",
                "last_name": "Smith",
                "email": "invalid-email-format",
            },
        )
        # Should render 200 with form errors, not redirect
        self.assertEqual(response.status_code, 200)
        form = response.context["profile_form"]
        self.assertTrue(form.is_bound)
        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)
        self.assertContains(response, "Enter a valid email address.")

    def test_profile_duplicate_email_validation(self):
        User.objects.create_user(
            username="otherlender",
            email="existing@example.com",
            password="Password123!",
        )
        self.client.force_login(self.user)
        response = self.client.post(
            self.settings_url,
            {
                "action": "profile",
                "first_name": "Janet",
                "last_name": "Smith",
                "email": "existing@example.com",
            },
        )
        self.assertEqual(response.status_code, 200)
        form = response.context["profile_form"]
        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)
        self.assertContains(response, "An account with this email address already exists.")

    def test_update_notification_preferences_turn_off_all(self):
        self.client.force_login(self.user)
        # Submitting preferences with unchecked checkboxes sends only action
        response = self.client.post(
            self.settings_url,
            {
                "action": "preferences",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        prefs = UserPreferences.objects.get(user=self.user)
        self.assertFalse(prefs.payment_reminders)
        self.assertFalse(prefs.due_date_reminders)
        messages = [m.message for m in get_messages(response.wsgi_request)]
        self.assertIn("Notification preferences updated successfully.", messages)

    def test_update_notification_preferences_independent_toggle(self):
        self.client.force_login(self.user)
        # Turn off both first
        prefs, _ = UserPreferences.objects.get_or_create(user=self.user)
        prefs.payment_reminders = False
        prefs.due_date_reminders = False
        prefs.save()

        # Turn on only payment_reminders
        self.client.post(
            self.settings_url,
            {
                "action": "preferences",
                "payment_reminders": "on",
            },
            follow=True,
        )
        prefs.refresh_from_db()
        self.assertTrue(prefs.payment_reminders)
        self.assertFalse(prefs.due_date_reminders)

        # Now turn on only due_date_reminders
        self.client.post(
            self.settings_url,
            {
                "action": "preferences",
                "due_date_reminders": "on",
            },
            follow=True,
        )
        prefs.refresh_from_db()
        self.assertFalse(prefs.payment_reminders)
        self.assertTrue(prefs.due_date_reminders)

    def test_preferences_persistence_on_page_reload(self):
        self.client.force_login(self.user)
        # Save payment_reminders=False, due_date_reminders=True
        self.client.post(
            self.settings_url,
            {
                "action": "preferences",
                "due_date_reminders": "on",
            },
            follow=True,
        )
        # Reload settings page
        response = self.client.get(self.settings_url)
        self.assertEqual(response.status_code, 200)
        prefs_form = response.context["preferences_form"]
        self.assertFalse(prefs_form.initial["payment_reminders"])
        self.assertTrue(prefs_form.initial["due_date_reminders"])

    def test_user_data_isolation(self):
        other_user = User.objects.create_user(
            username="otheruser",
            email="other@example.com",
            password="Password123!",
        )
        other_prefs = UserPreferences.objects.create(
            user=other_user,
            payment_reminders=False,
            due_date_reminders=False,
        )

        self.client.force_login(self.user)
        self.client.post(
            self.settings_url,
            {
                "action": "preferences",
                "payment_reminders": "on",
                "due_date_reminders": "on",
            },
            follow=True,
        )

        # Other user's preferences must remain unchanged
        other_prefs.refresh_from_db()
        self.assertFalse(other_prefs.payment_reminders)
        self.assertFalse(other_prefs.due_date_reminders)

    def test_whatsapp_notification_preferences_defaults_and_toggle(self):
        self.client.force_login(self.user)
        prefs, _ = UserPreferences.objects.get_or_create(user=self.user)
        # Verify safe default: WhatsApp notifications disabled initially
        self.assertFalse(prefs.whatsapp_notifications_enabled)

        # Enable WhatsApp notifications and specific categories
        response = self.client.post(
            self.settings_url,
            {
                "action": "preferences",
                "whatsapp_notifications_enabled": "on",
                "whatsapp_loan_created": "on",
                "whatsapp_payment_received": "on",
                "whatsapp_monthly_reminders": "on",
                "whatsapp_overdue_reminders": "on",
                "whatsapp_loan_closed": "on",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        prefs.refresh_from_db()
        self.assertTrue(prefs.whatsapp_notifications_enabled)
        self.assertTrue(prefs.whatsapp_loan_created)
        self.assertTrue(prefs.whatsapp_payment_received)
        self.assertTrue(prefs.whatsapp_monthly_reminders)
        self.assertTrue(prefs.whatsapp_overdue_reminders)
        self.assertTrue(prefs.whatsapp_loan_closed)

        # Disable master switch
        response = self.client.post(
            self.settings_url,
            {
                "action": "preferences",
                # no whatsapp_notifications_enabled sent -> unchecked
                "whatsapp_loan_created": "on",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        prefs.refresh_from_db()
        self.assertFalse(prefs.whatsapp_notifications_enabled)
        self.assertTrue(prefs.whatsapp_loan_created)
        self.assertFalse(prefs.whatsapp_payment_received)
