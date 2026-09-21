from getpass import getpass
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from inspections.models import User


class Command(BaseCommand):
    help = 'Create an inspector interactively without putting a password in shell history.'

    def add_arguments(self, parser):
        parser.add_argument('username')
        parser.add_argument('--name', default='')

    def handle(self, *args, **options):
        if User.objects.filter(username=options['username']).exists():
            raise CommandError('Username already exists; no account was changed.')
        user = User(username=options['username'], first_name=options['name'], role='INSPECTOR')
        password = getpass('Password: ')
        if password != getpass('Password (again): '):
            raise CommandError('Passwords do not match.')
        try:
            validate_password(password, user)
            user.set_password(password)
            user.full_clean()
            user.save()
        except ValidationError as error:
            raise CommandError('; '.join(error.messages)) from error
        self.stdout.write(self.style.SUCCESS('Inspector created.'))
