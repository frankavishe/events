from datetime import UTC, datetime
from decimal import Decimal

from django.db import migrations


def seed(apps, schema_editor):
    CommissionSetting = apps.get_model("ledger", "CommissionSetting")
    if not CommissionSetting.objects.exists():
        CommissionSetting.objects.create(
            rate=Decimal("0.1000"), effective_from=datetime(2026, 1, 1, tzinfo=UTC)
        )


class Migration(migrations.Migration):
    dependencies = [("ledger", "0002_initial")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
