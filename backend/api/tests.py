from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from .models import Whiskey, Review
from datetime import date

class WhiskeyTests(APITestCase):
    def setUp(self):
        self.whiskey = Whiskey.objects.create(
            name='Yamazaki 12',
            distillery='Suntory Yamazaki Distillery'
        )
        self.user_id = 'test-user-id'
        self.client.defaults['HTTP_AUTHORIZATION'] = f'Bearer fake-token'
        # Mock the middleware authentication
        self.client.handler._force_user_id = self.user_id

    def test_suggest_whiskey(self):
        url = reverse('whiskey-suggest')
        response = self.client.get(f'{url}?q=Yama')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['name'], 'Yamazaki 12')

class ReviewTests(APITestCase):
    def setUp(self):
        self.whiskey = Whiskey.objects.create(
            name='Yamazaki 12',
            distillery='Suntory Yamazaki Distillery'
        )
        self.user_id = 'test-user-id'
        self.client.defaults['HTTP_AUTHORIZATION'] = f'Bearer fake-token'
        # Mock the middleware authentication
        self.client.handler._force_user_id = self.user_id

    def test_create_review(self):
        url = reverse('review-list')
        data = {
            'whiskey': self.whiskey.id,
            'notes': 'Great whiskey',
            'rating': 5,
            'serving_style': 'NEAT',
            'date': date.today().isoformat()
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Review.objects.count(), 1)
        self.assertEqual(Review.objects.get().user_id, self.user_id)

    def test_list_reviews(self):
        Review.objects.create(
            whiskey=self.whiskey,
            user_id=self.user_id,
            notes='Great whiskey',
            rating=5,
            serving_style='NEAT',
            date=date.today()
        )
        url = reverse('review-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)

class StatsTests(APITestCase):
    def setUp(self):
        self.whiskey = Whiskey.objects.create(
            name='Yamazaki 12',
            distillery='Suntory Yamazaki Distillery'
        )
        self.user_id = 'test-user-id'
        self.client.defaults['HTTP_AUTHORIZATION'] = f'Bearer fake-token'
        # Mock the middleware authentication
        self.client.handler._force_user_id = self.user_id
        
        # Create some reviews
        Review.objects.create(
            whiskey=self.whiskey,
            user_id=self.user_id,
            notes='Great whiskey',
            rating=5,
            serving_style='NEAT',
            date=date.today()
        )

    def test_alcohol_stats(self):
        url = reverse('alcohol-stats')
        response = self.client.get(f'{url}?period=daily')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['servings'], 1)
        self.assertEqual(response.data[0]['total_ml'], 30)
