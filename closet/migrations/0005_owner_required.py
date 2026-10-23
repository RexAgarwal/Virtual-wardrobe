from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def owner(related):
    return models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name=related,
                             to=settings.AUTH_USER_MODEL)


class Migration(migrations.Migration):
    dependencies = [('closet', '0004_assign_demo_owner')]
    operations = [
        migrations.AlterField('item', 'owner', owner('items')),
        migrations.AlterField('outfit', 'owner', owner('outfits')),
        migrations.AlterField('trip', 'owner', owner('trips')),
        migrations.AlterField('plannedoutfit', 'owner', owner('plans')),
    ]
