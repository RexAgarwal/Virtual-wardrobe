from django.conf import settings
from django.db import migrations


def assign(apps, schema_editor):
    """Everything made before accounts existed goes to a 'demo' user, so nothing is lost."""
    User = apps.get_model(*settings.AUTH_USER_MODEL.split('.'))
    models = [apps.get_model('closet', n) for n in ('Item', 'Outfit', 'Trip', 'PlannedOutfit')]
    if not any(m.objects.filter(owner__isnull=True).exists() for m in models):
        return
    demo, _ = User.objects.get_or_create(username='demo', defaults={'password': '!'})  # '!' = cannot log in
    for m in models:
        m.objects.filter(owner__isnull=True).update(owner=demo)


class Migration(migrations.Migration):
    dependencies = [('closet', '0003_add_owner')]
    operations = [migrations.RunPython(assign, migrations.RunPython.noop)]
