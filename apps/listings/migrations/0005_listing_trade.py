# Generated for exchange option

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('listings', '0004_plain_labels'),
    ]

    operations = [
        migrations.AddField(
            model_name='listing',
            name='open_to_trade',
            field=models.BooleanField(default=False, verbose_name='مایل به معاوضه هستم'),
        ),
        migrations.AddField(
            model_name='listing',
            name='trade_with',
            field=models.CharField(blank=True, max_length=200, verbose_name='با چی معاوضه می\u200cکنم؟'),
        ),
    ]
