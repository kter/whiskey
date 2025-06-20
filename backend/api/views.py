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
from rest_framework.decorators import api_view
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
import boto3
from .dynamodb_service import DynamoDBService
from .serializers import WhiskeySerializer, ReviewSerializer, UserProfileSerializer
import logging

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
        logger = logging.getLogger(__name__)
        
        user_id = getattr(request, 'user_id', None)
        logger.info(f"Review creation request - user_id: {user_id}")
        
        if not user_id:
            return Response({'error': 'Authentication required'}, status=status.HTTP_401_UNAUTHORIZED)
        
        logger.info(f"Request data: {request.data}")
        
        serializer = ReviewSerializer(data=request.data)
        if serializer.is_valid():
            validated_data = serializer.validated_data
            logger.info(f"Validated data: {validated_data}")
            
            # フロントエンドから受信したウィスキー情報で新しいウィスキーを作成
            whiskey_name = request.data.get('whiskey_name', 'Unknown')
            whiskey_distillery = request.data.get('whiskey_distillery', 'Unknown')
            logger.info(f"Whiskey info - name: {whiskey_name}, distillery: {whiskey_distillery}")
            
            # 既存のウィスキーを検索（名前と蒸留所が完全一致）
            existing_whiskeys = self.db_service.search_whiskeys(whiskey_name)
            whiskey = None
            logger.info(f"Found {len(existing_whiskeys)} existing whiskeys matching '{whiskey_name}'")
            
            for existing_whiskey in existing_whiskeys:
                if (existing_whiskey['name'].lower() == whiskey_name.lower() and 
                    existing_whiskey.get('distillery', '').lower() == whiskey_distillery.lower()):
                    whiskey = existing_whiskey
                    logger.info(f"Found matching whiskey: {whiskey['id']}")
                    break
            
            # 既存のウィスキーが見つからない場合は新規作成
            if not whiskey:
                logger.info("Creating new whiskey")
                try:
                    whiskey = self.db_service.create_whiskey(whiskey_name, whiskey_distillery)
                    logger.info(f"Created new whiskey: {whiskey['id']}")
                except Exception as e:
                    logger.error(f"Error creating whiskey: {e}")
                    return Response({'error': f'Failed to create whiskey: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            whiskey_id = whiskey['id']
            
            # whiskeyフィールドを削除（使わない）
            validated_data.pop('whiskey', None)
            
            # レビューを作成
            try:
                logger.info(f"Creating review for whiskey_id: {whiskey_id}")
                review = self.db_service.create_review(
                    whiskey_id=whiskey_id,
                    user_id=user_id,
                    notes=validated_data['notes'],
                    rating=validated_data['rating'],
                    serving_style=validated_data['serving_style'],
                    review_date=validated_data['date'],
                    image_url=validated_data.get('image_url')
                )
                logger.info(f"Created review: {review['id']}")
            except Exception as e:
                logger.error(f"Error creating review: {e}")
                return Response({'error': f'Failed to create review: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            # ウィスキー情報を付加
            review['whiskey_name'] = whiskey['name']
            review['whiskey_distillery'] = whiskey['distillery']
            
            return Response(review, status=status.HTTP_201_CREATED)
        else:
            logger.error(f"Serializer validation errors: {serializer.errors}")
        
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
    """ウィスキー検索API - 既存ウィスキーテーブルから検索"""
    
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


class WhiskeySearchSuggestView(APIView):
    """ウィスキー検索API - 検索最適化テーブルから日本語検索"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db_service = DynamoDBService()
    
    def get(self, request):
        """
        日本語でのインクリメンタル検索
        ?q=検索クエリ&limit=10
        """
        q = request.query_params.get('q', '').strip()
        limit = int(request.query_params.get('limit', 10))
        
        # 最小文字数チェック
        if len(q) < 1:
            return Response([])
        
        # 最大制限
        limit = min(limit, 50)
        
        try:
            # 検索実行
            suggestions = self.db_service.search_whiskey_suggestions(q, limit)
            
            # レスポンス形式を整形
            formatted_suggestions = []
            for suggestion in suggestions:
                formatted_suggestions.append({
                    'id': suggestion.get('id'),
                    'name_ja': suggestion.get('name_ja', ''),
                    'name_en': suggestion.get('name_en', ''),
                    'distillery_ja': suggestion.get('distillery_ja', ''),
                    'distillery_en': suggestion.get('distillery_en', ''),
                    'region': suggestion.get('region', ''),
                    'type': suggestion.get('type', ''),
                    'description': suggestion.get('description_ja', suggestion.get('description', ''))[:100] + '...' if suggestion.get('description_ja', suggestion.get('description', '')) else ''
                })
            
            return Response({
                'query': q,
                'suggestions': formatted_suggestions,
                'total': len(formatted_suggestions)
            })
            
        except Exception as e:
            logger.error(f"Search error: {e}")
            return Response({
                'query': q,
                'suggestions': [],
                'total': 0,
                'error': 'Search temporarily unavailable'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class WhiskeySearchView(APIView):
    """ウィスキー詳細検索API"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db_service = DynamoDBService()
    
    def get(self, request):
        """
        詳細検索
        ?name=名前&distillery=蒸留所&region=地域&type=タイプ&limit=20
        """
        name = request.query_params.get('name', '').strip()
        distillery = request.query_params.get('distillery', '').strip()
        region = request.query_params.get('region', '').strip()
        whiskey_type = request.query_params.get('type', '').strip()
        limit = int(request.query_params.get('limit', 20))
        
        # 最大制限
        limit = min(limit, 100)
        
        try:
            results = []
            
            # 各条件で検索して結果をマージ
            if name:
                name_results = self.db_service.search_whiskey_suggestions(name, limit)
                results.extend(name_results)
            
            if distillery:
                distillery_results = self.db_service.search_whiskey_suggestions(distillery, limit)
                results.extend(distillery_results)
            
            # 重複除去とフィルタリング
            seen_ids = set()
            filtered_results = []
            
            for result in results:
                if result['id'] in seen_ids:
                    continue
                
                # 地域フィルタ
                if region and region.lower() not in result.get('region', '').lower():
                    continue
                
                # タイプフィルタ
                if whiskey_type and whiskey_type.lower() not in result.get('type', '').lower():
                    continue
                
                seen_ids.add(result['id'])
                filtered_results.append(result)
                
                if len(filtered_results) >= limit:
                    break
            
            return Response({
                'filters': {
                    'name': name,
                    'distillery': distillery,
                    'region': region,
                    'type': whiskey_type
                },
                'results': filtered_results[:limit],
                'total': len(filtered_results)
            })
            
        except Exception as e:
            logger.error(f"Advanced search error: {e}")
            return Response({
                'filters': {},
                'results': [],
                'total': 0,
                'error': 'Search temporarily unavailable'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class WhiskeyRankingView(APIView):
    """ウィスキーランキングAPI"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db_service = DynamoDBService()
    
    def get(self, request):
        whiskeys = self.db_service.get_whiskey_ranking()
        serializer = WhiskeySerializer(whiskeys, many=True)
        return Response(serializer.data)

@method_decorator(csrf_exempt, name='dispatch')
class PublicReviewsView(APIView):
    """パブリックレビュー一覧API（認証不要）"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db_service = DynamoDBService()
    
    def options(self, request, *args, **kwargs):
        """CORS preflight request handling"""
        response = Response()
        response['Access-Control-Allow-Origin'] = request.META.get('HTTP_ORIGIN', '*')
        response['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        response['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        response['Access-Control-Allow-Credentials'] = 'true'
        return response
    
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
        response = JsonResponse({
            'status': 'healthy',
            'service': 'whiskey-api',
            'timestamp': timezone.now().isoformat()
        })
        # CORSヘッダーを明示的に追加
        response['Access-Control-Allow-Origin'] = '*'
        response['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        response['Access-Control-Allow-Headers'] = 'Content-Type'
        return response


class UserProfileViewSet(viewsets.ViewSet):
    """ユーザープロフィール管理用ViewSet"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db_service = DynamoDBService()
    
    def retrieve(self, request, pk=None):
        """ユーザープロフィールを取得 (GET /api/users/profile/)"""
        user_id = getattr(request, 'user_id', None)
        if not user_id:
            return Response({'error': 'Authentication required'}, status=status.HTTP_401_UNAUTHORIZED)
        
        try:
            profile = self.db_service.get_user_profile(user_id)
            if profile:
                return Response(profile)
            else:
                return Response({'error': 'Profile not found'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def create(self, request):
        """ユーザープロフィールを作成 (POST /api/users/profile/)"""
        user_id = getattr(request, 'user_id', None)
        if not user_id:
            return Response({'error': 'Authentication required'}, status=status.HTTP_401_UNAUTHORIZED)
        
        serializer = UserProfileSerializer(data=request.data)
        if serializer.is_valid():
            try:
                profile = self.db_service.create_user_profile(
                    user_id=user_id,
                    nickname=serializer.validated_data['nickname'],
                    display_name=serializer.validated_data.get('display_name')
                )
                return Response(profile, status=status.HTTP_201_CREATED)
            except ValueError as e:
                return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def update(self, request, pk=None):
        """ユーザープロフィールを更新 (PUT /api/users/profile/)"""
        user_id = getattr(request, 'user_id', None)
        if not user_id:
            return Response({'error': 'Authentication required'}, status=status.HTTP_401_UNAUTHORIZED)
        
        serializer = UserProfileSerializer(data=request.data, partial=True)
        if serializer.is_valid():
            try:
                profile = self.db_service.update_user_profile(
                    user_id=user_id,
                    nickname=serializer.validated_data.get('nickname'),
                    display_name=serializer.validated_data.get('display_name')
                )
                return Response(profile)
            except ValueError as e:
                return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def get_or_create_profile(self, request):
        """プロフィールを取得、存在しない場合はデフォルトで作成 (POST /api/users/profile/get-or-create/)"""
        user_id = getattr(request, 'user_id', None)
        if not user_id:
            return Response({'error': 'Authentication required'}, status=status.HTTP_401_UNAUTHORIZED)
        
        try:
            # デフォルトニックネームを生成
            import random
            
            # 称号のような親しみやすい形容詞
            title_words = [
                'エレガントな', '情熱的な', '洗練された', '優雅な', '熟練の',
                '神秘的な', '伝説の', '華麗なる', '至高の', '究極の',
                '魅惑的な', '上品な', '贅沢な', '格調高い', '気品ある',
                '卓越した', '素晴らしい', '見事な', '美しき', '誇り高き',
                '知的な', '穏やかな', '温和な', '心優しい', '勇敢な',
                '冒険好きな', '探究心旺盛な', '好奇心強い', '学習熱心な', '研究熱心な',
                'ロマンチックな', 'クラシックな', 'モダンな', 'スタイリッシュな', 'シャープな'
            ]
            
            # ウイスキー関連用語
            whiskey_terms = [
                'ウイスキー愛好家', 'テイスター', 'ウイスキーファン', 
                'スコッチ愛好家', 'バーボン好き', '蒸留酒マニア',
                'モルト探検家', 'ウイスキー初心者', '樽の番人',
                'シングルモルト好き', 'ブレンド愛好家', 'カスク探求者',
                'アンバー愛好家', 'ピート好き', 'シェリーカスク派',
                'ハイランド好き', 'アイラ島愛好家', 'スペイサイド派'
            ]
            
            # ランダムに組み合わせて生成
            title = random.choice(title_words)
            whiskey_term = random.choice(whiskey_terms)
            default_nickname = f'{title}{whiskey_term}'
            
            profile = self.db_service.get_or_create_user_profile(user_id, default_nickname)
            return Response(profile)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
