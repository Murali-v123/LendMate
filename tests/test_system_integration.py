"""
End-to-end integration and smoke tests verifying that the reorganized
LendMate structure loads all templates, static assets, backend models,
and notification workflows cleanly.
"""
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.conf import settings

User = get_user_model()


class ProjectStructureSmokeTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="testadmin",
            password="adminpassword123",
            email="admin@lendmate.local",
        )

    def test_frontend_templates_directory_configured(self):
        """Verify templates directory points to frontend/templates."""
        template_dirs = settings.TEMPLATES[0]["DIRS"]
        self.assertTrue(
            any("frontend" in str(d) and "templates" in str(d) for d in template_dirs),
            f"Expected frontend/templates in TEMPLATES DIRS: {template_dirs}",
        )

    def test_frontend_static_directory_configured(self):
        """Verify static files directory points to frontend/static."""
        static_dirs = settings.STATICFILES_DIRS
        self.assertTrue(
            any("frontend" in str(d) and "static" in str(d) for d in static_dirs),
            f"Expected frontend/static in STATICFILES_DIRS: {static_dirs}",
        )

    def test_login_page_renders_frontend_template(self):
        """Verify login page renders correctly from frontend/templates/accounts/login.html."""
        response = self.client.get(reverse("accounts:login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sign in to LendMate")
        self.assertContains(response, "/static/css/lendmate.css")

    def test_authenticated_dashboard_renders(self):
        """Verify dashboard renders for logged-in lender."""
        self.client.login(username="testadmin", password="adminpassword123")
        response = self.client.get(reverse("core:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dashboard")

    def test_notification_history_renders(self):
        """Verify notification history view renders properly."""
        self.client.login(username="testadmin", password="adminpassword123")
        response = self.client.get(reverse("notifications:history"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "SMS Notifications")

    def test_health_check_endpoint(self):
        """Verify deployment health endpoint returns status 200."""
        response = self.client.get("/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
