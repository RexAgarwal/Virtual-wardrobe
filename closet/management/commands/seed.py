from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from closet.samples import load_samples


class Command(BaseCommand):
    help = 'Add sample pieces and outfits (generated images) to an account: manage.py seed USERNAME'

    def add_arguments(self, parser):
        parser.add_argument('username')

    def handle(self, *args, username, **opts):
        try:
            user = get_user_model().objects.get(username=username)
        except get_user_model().DoesNotExist:
            raise CommandError(f'No account called {username!r}.')
        load_samples(user)
        self.stdout.write(self.style.SUCCESS(f'{user.items.count()} pieces, {user.outfits.count()} outfits for {username}.'))
