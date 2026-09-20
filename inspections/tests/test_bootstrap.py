from django.test import TestCase
from inspections.models import User

class AuthenticationTests(TestCase):
    def test_anonymous_redirected(self):
        self.assertRedirects(self.client.get('/'), '/accounts/login/?next=/', fetch_redirect_response=False)

    def test_authenticated_user_can_open_workspace(self):
        user = User.objects.create_user('inspector', password='example-strong-pass')
        self.client.force_login(user)
        self.assertEqual(self.client.get('/').status_code, 200)

    def test_superuser_has_administrative_role(self):
        user = User.objects.create_superuser('admin', password='example-strong-pass')
        self.assertTrue(user.is_admin)
        self.assertEqual(user.role, User.Role.ADMIN)
