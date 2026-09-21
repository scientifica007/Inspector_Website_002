from django.test import TestCase
from django.core.management import call_command, CommandError
from io import StringIO
from unittest.mock import patch
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

    def test_create_inspector_command_validates_password_and_preserves_existing_account(self):
        with patch('inspections.management.commands.create_inspector.getpass', return_value='x'):
            with self.assertRaises(CommandError):
                call_command('create_inspector', 'field_inspector', stdout=StringIO())
        self.assertFalse(User.objects.filter(username='field_inspector').exists())
        with patch('inspections.management.commands.create_inspector.getpass', return_value='Strong-test-password-9642'):
            call_command('create_inspector', 'field_inspector', name='مفتش ميداني', stdout=StringIO())
        user = User.objects.get(username='field_inspector')
        self.assertEqual(user.role, 'INSPECTOR')
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.check_password('Strong-test-password-9642'))
        with self.assertRaises(CommandError):
            call_command('create_inspector', 'field_inspector', stdout=StringIO())
        user.refresh_from_db()
        self.assertTrue(user.check_password('Strong-test-password-9642'))
