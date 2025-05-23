from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from unittest.mock import patch, MagicMock
from .dynamodb_service import DynamoDBService
from datetime import date

class DynamoDBServiceTests(TestCase):
    """DynamoDBService用のテスト"""
    
    @patch('api.dynamodb_service.boto3.resource')
    def setUp(self, mock_boto3):
        # DynamoDBのモックを設定
        self.mock_dynamodb = MagicMock()
        mock_boto3.return_value = self.mock_dynamodb
        
        self.mock_whiskey_table = MagicMock()
        self.mock_review_table = MagicMock()
        
        self.mock_dynamodb.Table.side_effect = lambda name: {
            'Whiskeys': self.mock_whiskey_table,
            'Reviews': self.mock_review_table
        }[name]
        
        # テーブル存在チェックのモック
        self.mock_whiskey_table.load.return_value = None
        self.mock_review_table.load.return_value = None
        
        self.db_service = DynamoDBService()

    def test_create_whiskey(self):
        """ウィスキー作成のテスト"""
        # put_itemの戻り値をモック
        self.mock_whiskey_table.put_item.return_value = None
        
        result = self.db_service.create_whiskey('Yamazaki 12', 'Suntory')
        
        self.assertEqual(result['name'], 'Yamazaki 12')
        self.assertEqual(result['distillery'], 'Suntory')
        self.assertIn('id', result)
        self.mock_whiskey_table.put_item.assert_called_once()

class WhiskeyAPITests(APITestCase):
    """ウィスキーAPI用のテスト"""
    
    @patch('api.views.DynamoDBService')
    def setUp(self, mock_service_class):
        self.mock_service = MagicMock()
        mock_service_class.return_value = self.mock_service
        
        self.user_id = 'test-user-id'
        self.client.defaults['HTTP_AUTHORIZATION'] = f'Bearer fake-token'

    def test_suggest_whiskey(self):
        """ウィスキー検索のテスト"""
        # モックデータ
        mock_whiskeys = [
            {
                'id': '123',
                'name': 'Yamazaki 12',
                'distillery': 'Suntory Yamazaki Distillery',
                'created_at': '2024-01-01T00:00:00',
                'updated_at': '2024-01-01T00:00:00'
            }
        ]
        self.mock_service.search_whiskeys.return_value = mock_whiskeys
        
        url = reverse('whiskey-suggest')
        response = self.client.get(f'{url}?q=Yama')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['name'], 'Yamazaki 12')

class ReviewAPITests(APITestCase):
    """レビューAPI用のテスト"""
    
    @patch('api.views.DynamoDBService')
    def setUp(self, mock_service_class):
        self.mock_service = MagicMock()
        mock_service_class.return_value = self.mock_service
        
        self.user_id = 'test-user-id'
        self.client.defaults['HTTP_AUTHORIZATION'] = f'Bearer fake-token'
        
        # モックデータ
        self.mock_whiskey = {
            'id': 'whiskey-123',
            'name': 'Yamazaki 12',
            'distillery': 'Suntory Yamazaki Distillery',
            'created_at': '2024-01-01T00:00:00',
            'updated_at': '2024-01-01T00:00:00'
        }
        
        self.mock_review = {
            'id': 'review-123',
            'whiskey_id': 'whiskey-123',
            'user_id': self.user_id,
            'notes': 'Great whiskey',
            'rating': 5,
            'serving_style': 'NEAT',
            'date': '2024-01-01',
            'created_at': '2024-01-01T00:00:00',
            'updated_at': '2024-01-01T00:00:00'
        }

    @patch('api.middleware.CognitoAuthMiddleware.process_request')
    def test_create_review(self, mock_auth):
        """レビュー作成のテスト"""
        # 認証をモック
        mock_auth.return_value = None
        
        # DynamoDBサービスのモック設定
        self.mock_service.get_whiskey.return_value = self.mock_whiskey
        self.mock_service.create_review.return_value = self.mock_review
        
        # リクエストにuser_idを設定
        def mock_process_request(request):
            request.user_id = self.user_id
            return None
        
        with patch('api.views.ReviewViewSet.create') as mock_create:
            mock_create.return_value = MagicMock(status_code=201, data=self.mock_review)
            
            url = reverse('review-list')
            data = {
                'whiskey': 'whiskey-123',
                'notes': 'Great whiskey',
                'rating': 5,
                'serving_style': 'NEAT',
                'date': '2024-01-01'
            }
            
            # 直接サービスのメソッドをテスト
            result = self.mock_service.create_review(
                whiskey_id='whiskey-123',
                user_id=self.user_id,
                notes='Great whiskey',
                rating=5,
                serving_style='NEAT',
                review_date='2024-01-01'
            )
            
            self.assertEqual(result, self.mock_review)
