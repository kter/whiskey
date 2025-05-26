from django.shortcuts import render
from django.http import JsonResponse
from django.views import View
from django.utils import timezone
import os
from datetime import datetime
from rest_framework import viewsets, generics, status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination
import boto3
from .dynamodb_service import DynamoDBService
from .serializers import WhiskeySerializer, ReviewSerializer

# Create your views here.

class ReviewViewSet(viewsets.ViewSet):
    """DynamoDB用のReviewViewSet"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db_service = DynamoDBService()
    
    def list(self, request):
        """レビュー一覧を取得"""
        user_id = getattr(request, 'user_id', None)
        if not user_id:
            return Response({'error': 'Authentication required'}, status=status.HTTP_401_UNAUTHORIZED)
        
        page = int(request.query_params.get('page', 1))
        per_page = int(request.query_params.get('per_page', 10))
        
        result = self.db_service.get_user_reviews(user_id, page, per_page)
        
        # ウィスキー情報を付加
        for review in result['results']:
            whiskey = self.db_service.get_whiskey(review['whiskey_id'])
            if whiskey:
                review['whiskey_name'] = whiskey['name']
                review['whiskey_distillery'] = whiskey['distillery']
        
        return Response(result)
    
    def create(self, request):
        """レビューを作成"""
        user_id = getattr(request, 'user_id', None)
        if not user_id:
            return Response({'error': 'Authentication required'}, status=status.HTTP_401_UNAUTHORIZED)
        
        serializer = ReviewSerializer(data=request.data)
        if serializer.is_valid():
            validated_data = serializer.validated_data
            
            # ウィスキーの存在確認または作成
            whiskey_id = validated_data.pop('whiskey')
            whiskey = self.db_service.get_whiskey(whiskey_id)
            
            if not whiskey:
                # 新しいウィスキーの場合、フロントエンドから追加情報が必要
                whiskey_name = request.data.get('whiskey_name', 'Unknown')
                whiskey_distillery = request.data.get('whiskey_distillery', 'Unknown')
                whiskey = self.db_service.create_whiskey(whiskey_name, whiskey_distillery)
                whiskey_id = whiskey['id']
            
            # レビューを作成
            review = self.db_service.create_review(
                whiskey_id=whiskey_id,
                user_id=user_id,
                notes=validated_data['notes'],
                rating=validated_data['rating'],
                serving_style=validated_data['serving_style'],
                review_date=validated_data['date'],
                image_url=validated_data.get('image_url')
            )
            
            # ウィスキー情報を付加
            review['whiskey_name'] = whiskey['name']
            review['whiskey_distillery'] = whiskey['distillery']
            
            return Response(review, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def retrieve(self, request, pk=None):
        """特定のレビューを取得"""
        review = self.db_service.get_review(pk)
        if not review:
            return Response({'error': 'Review not found'}, status=status.HTTP_404_NOT_FOUND)
        
        # ウィスキー情報を付加
        whiskey = self.db_service.get_whiskey(review['whiskey_id'])
        if whiskey:
            review['whiskey_name'] = whiskey['name']
            review['whiskey_distillery'] = whiskey['distillery']
        
        return Response(review)
    
    def update(self, request, pk=None):
        """レビューを更新"""
        user_id = getattr(request, 'user_id', None)
        if not user_id:
            return Response({'error': 'Authentication required'}, status=status.HTTP_401_UNAUTHORIZED)
        
        review = self.db_service.get_review(pk)
        if not review:
            return Response({'error': 'Review not found'}, status=status.HTTP_404_NOT_FOUND)
        
        if review['user_id'] != user_id:
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        
        serializer = ReviewSerializer(data=request.data, partial=True)
        if serializer.is_valid():
            validated_data = serializer.validated_data
            validated_data.pop('whiskey', None)  # ウィスキーは変更不可
            
            updated_review = self.db_service.update_review(pk, validated_data)
            
            # ウィスキー情報を付加
            whiskey = self.db_service.get_whiskey(updated_review['whiskey_id'])
            if whiskey:
                updated_review['whiskey_name'] = whiskey['name']
                updated_review['whiskey_distillery'] = whiskey['distillery']
            
            return Response(updated_review)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def destroy(self, request, pk=None):
        """レビューを削除"""
        user_id = getattr(request, 'user_id', None)
        if not user_id:
            return Response({'error': 'Authentication required'}, status=status.HTTP_401_UNAUTHORIZED)
        
        review = self.db_service.get_review(pk)
        if not review:
            return Response({'error': 'Review not found'}, status=status.HTTP_404_NOT_FOUND)
        
        if review['user_id'] != user_id:
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        
        success = self.db_service.delete_review(pk)
        if success:
            return Response(status=status.HTTP_204_NO_CONTENT)
        else:
            return Response({'error': 'Failed to delete review'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class WhiskeySuggestView(APIView):
    """ウィスキー検索API"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db_service = DynamoDBService()
    
    def get(self, request):
        q = request.query_params.get('q', '')
        if len(q) < 2:
            return Response([])
        
        whiskeys = self.db_service.search_whiskeys(q)
        serializer = WhiskeySerializer(whiskeys, many=True)
        return Response(serializer.data)

class WhiskeyRankingView(APIView):
    """ウィスキーランキングAPI"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db_service = DynamoDBService()
    
    def get(self, request):
        whiskeys = self.db_service.get_whiskey_ranking()
        serializer = WhiskeySerializer(whiskeys, many=True)
        return Response(serializer.data)

class PublicReviewsView(APIView):
    """パブリックレビュー一覧API（認証不要）"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db_service = DynamoDBService()
    
    def get(self, request):
        page = int(request.query_params.get('page', 1))
        per_page = int(request.query_params.get('per_page', 10))
        
        # 全てのレビューを取得（認証不要版）
        result = self.db_service.get_all_reviews(page, per_page)
        
        # ウィスキー情報を付加
        for review in result['results']:
            whiskey = self.db_service.get_whiskey(review['whiskey_id'])
            if whiskey:
                review['whiskey_name'] = whiskey['name']
                review['whiskey_distillery'] = whiskey['distillery']
        
        return Response(result)

class S3UploadUrlView(APIView):
    """S3アップロードURL生成API"""
    
    def get(self, request):
        s3_client = boto3.client('s3')
        bucket = os.getenv('AWS_S3_BUCKET')
        
        # Generate a unique file name
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        user_id = getattr(request, 'user_id', 'anonymous')
        key = f'reviews/{user_id}/{timestamp}.jpg'
        
        # Generate presigned URL for upload
        url = s3_client.generate_presigned_url(
            'put_object',
            Params={
                'Bucket': bucket,
                'Key': key,
                'ContentType': 'image/jpeg'
            },
            ExpiresIn=300  # URL expires in 5 minutes
        )
        
        return Response({
            'upload_url': url,
            'image_url': f'https://{bucket}.s3.amazonaws.com/{key}'
        })


class HealthCheckView(View):
    """
    ヘルスチェック用のエンドポイント
    ALB/ECSのヘルスチェックで使用される
    """
    def get(self, request):
        return JsonResponse({
            'status': 'healthy',
            'service': 'whiskey-api',
            'timestamp': timezone.now().isoformat()
        })
