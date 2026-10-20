from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0004_company_payload'),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                "ALTER TABLE companies "
                "MODIFY created_at datetime(6) NOT NULL AFTER payload, "
                "MODIFY updated_at datetime(6) NOT NULL AFTER created_at"
            ),
            reverse_sql=(
                "ALTER TABLE companies "
                "MODIFY created_at datetime(6) NOT NULL AFTER twitter_url, "
                "MODIFY updated_at datetime(6) NOT NULL AFTER created_at"
            ),
        ),
    ]
