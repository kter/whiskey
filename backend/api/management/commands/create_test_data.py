from django.core.management.base import BaseCommand
from api.models import Whiskey, Review
from datetime import date, timedelta
import random

class Command(BaseCommand):
    help = 'Creates test data for development'

    def handle(self, *args, **options):
        # Create test whiskeys
        whiskeys = [
            ('山崎 12年', 'サントリー山崎蒸溜所'),
            ('響 17年', 'サントリー'),
            ('白州 12年', 'サントリー白州蒸溜所'),
            ('竹鶴 17年', 'ニッカウヰスキー余市蒸溜所'),
            ('余市', 'ニッカウヰスキー余市蒸溜所'),
            ('知多', 'サントリー知多蒸溜所'),
            ('イチローズモルト', 'ベンチャーウイスキー'),
            ('駒ヶ岳', 'マルスウイスキー'),
            ('富士山麓', '富士御殿場蒸溜所'),
            ('ニッカ フロム ザ バレル', 'ニッカウヰスキー'),
        ]

        created_whiskeys = []
        for name, distillery in whiskeys:
            whiskey, created = Whiskey.objects.get_or_create(
                name=name,
                distillery=distillery
            )
            created_whiskeys.append(whiskey)
            if created:
                self.stdout.write(f'Created whiskey: {name}')

        # Create test reviews
        test_user_id = 'test-user-123'
        serving_styles = [choice[0] for choice in Review.ServingStyle.choices]
        
        # Create reviews for the last 30 days
        for i in range(30):
            review_date = date.today() - timedelta(days=i)
            # Some days have multiple reviews
            for _ in range(random.randint(0, 2)):
                whiskey = random.choice(created_whiskeys)
                Review.objects.create(
                    whiskey=whiskey,
                    user_id=test_user_id,
                    notes=f'Test review for {whiskey.name}',
                    rating=random.randint(1, 5),
                    serving_style=random.choice(serving_styles),
                    date=review_date
                )

        self.stdout.write(self.style.SUCCESS('Successfully created test data')) 