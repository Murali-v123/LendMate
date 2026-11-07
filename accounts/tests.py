from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.urls import reverse


class AuthenticationTests(TestCase):
    password = "Sup3r-secret-pass"

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("core:dashboard"))
        self.assertRedirects(
            response,
            f"{reverse('accounts:login')}?next={reverse('core:dashboard')}",
        )

    def test_registration_creates_lender_and_signs_in(self):
        response = self.client.post(
            reverse("accounts:register"),
            {
                "full_name": "Asha Rao",
                "username": "asha",
                "email": "Asha@Example.com",
                "password1": self.password,
                "password2": self.password,
            },
        )
        self.assertRedirects(response, reverse("core:dashboard"))
        user = User.objects.get(username="asha")
        self.assertEqual(user.first_name, "Asha Rao")
        self.assertEqual(user.email, "asha@example.com")
        self.assertTrue(user.check_password(self.password))
        self.assertNotEqual(user.password, self.password)

    def test_registration_rejects_duplicate_email(self):
        User.objects.create_user("existing", email="taken@example.com", password=self.password)
        response = self.client.post(
            reverse("accounts:register"),
            {
                "full_name": "Other Person",
                "username": "other",
                "email": "TAKEN@example.com",
                "password1": self.password,
                "password2": self.password,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="other").exists())

    def test_login_and_logout_round_trip(self):
        User.objects.create_user("ravi", email="ravi@example.com", password=self.password)
        response = self.client.post(
            reverse("accounts:login"), {"username": "ravi", "password": self.password}
        )
        self.assertRedirects(response, reverse("core:dashboard"))
        self.assertEqual(self.client.get(reverse("core:dashboard")).status_code, 200)

        # Logout must be POST-only.
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)
        self.client.post(reverse("accounts:logout"))
        self.assertRedirects(
            self.client.get(reverse("core:dashboard")),
            f"{reverse('accounts:login')}?next={reverse('core:dashboard')}",
        )

    def test_password_reset_sends_email_to_registered_address(self):
        User.objects.create_user("meera", email="meera@example.com", password=self.password)
        self.client.post(reverse("accounts:password_reset"), {"email": "meera@example.com"})
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["meera@example.com"])
        self.assertIn("/accounts/password/reset/", mail.outbox[0].body)

    def test_settings_page_renders_for_signed_in_user(self):
        User.objects.create_user("kiran", email="kiran@example.com", password=self.password)
        self.client.login(username="kiran", password=self.password)
        response = self.client.get(reverse("core:settings"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "kiran@example.com")
