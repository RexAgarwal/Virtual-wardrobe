from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Move everything from the 'demo' account (made before accounts existed) to a real account: manage.py claim USERNAME"

    def add_arguments(self, parser):
        parser.add_argument('username')

    def handle(self, *args, username, **opts):
        User = get_user_model()
        try:
            me, demo = User.objects.get(username=username), User.objects.get(username='demo')
        except User.DoesNotExist:
            raise CommandError('Needs both the account you name and the old demo account.')
        moved = {}
        for rel in ('items', 'outfits', 'trips', 'plans'):
            rows = getattr(demo, rel)
            if rel == 'plans':  # one plan per day per person: leave days you already planned
                rows = rows.exclude(date__in=me.plans.values('date'))
            moved[rel] = rows.update(owner=me)
        self.stdout.write(self.style.SUCCESS(f'Moved to {username}: ' + ', '.join(f'{n} {k}' for k, n in moved.items())))
