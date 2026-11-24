from django.db import migrations

CATEGORIES = [
    ("main-dishes", "Main dishes", "Vyakula vikuu", "food"),
    ("snacks", "Snacks", "Vitafunwa", "food"),
    ("desserts", "Desserts", "Vitindamlo", "food"),
    ("soft-drinks", "Soft drinks", "Soda", "drink"),
    ("juice", "Juice", "Juisi", "drink"),
    ("water", "Water", "Maji", "drink"),
    ("beer", "Beer", "Bia", "drink"),
    ("wine", "Wine", "Mvinyo", "drink"),
    ("spirits", "Spirits", "Pombe kali", "drink"),
]


def seed(apps, schema_editor):
    Category = apps.get_model("catalog", "Category")
    for slug, name_en, name_sw, kind in CATEGORIES:
        Category.objects.get_or_create(
            slug=slug, defaults={"name_en": name_en, "name_sw": name_sw, "kind": kind}
        )


class Migration(migrations.Migration):
    dependencies = [("catalog", "0001_initial")]

    # Reversing keeps the rows: items may already reference them.
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
