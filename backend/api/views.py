from django.shortcuts import render
import os
from datetime import datetime, timedelta
from django.db.models import Avg, Count
from django.db.models.functions import TruncDate, TruncWeek, TruncMonth
from rest_framework import viewsets, generics, status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.views import APIView
import boto3
from .models import Whiskey, Review
from .serializers import WhiskeySerializer, ReviewSerializer

# Create your views here.

class ReviewViewSet(viewsets.ModelViewSet):
    serializer_class = ReviewSerializer

    def get_queryset(self):
        return Review.objects.filter(user_id=self.request.user_id).select_related('whiskey')

class WhiskeySuggestView(APIView):
    def get(self, request):
        q = request.query_params.get('q', '')
        if len(q) < 2:
            return Response([])
        
        whiskeys = Whiskey.objects.filter(name__icontains=q)[:10]
        return Response(WhiskeySerializer(whiskeys, many=True).data)

class WhiskeyRankingView(APIView):
    def get(self, request):
        whiskeys = Whiskey.objects.annotate(
            avg_rating=Avg('reviews__rating'),
            review_count=Count('reviews')
        ).filter(review_count__gt=0).order_by('-avg_rating')[:10]
        
        return Response(WhiskeySerializer(whiskeys, many=True).data)

class AlcoholStatsView(APIView):
    SERVING_SIZE_ML = 30  # 1杯 = 30ml

    def get(self, request):
        period = request.query_params.get('period', 'daily')
        user_id = request.user_id
        
        if period == 'daily':
            trunc_func = TruncDate
            days = 30
        elif period == 'weekly':
            trunc_func = TruncWeek
            days = 90
        else:  # monthly
            trunc_func = TruncMonth
            days = 365
            
        start_date = datetime.now() - timedelta(days=days)
        
        stats = Review.objects.filter(
            user_id=user_id,
            date__gte=start_date
        ).annotate(
            period_date=trunc_func('date')
        ).values('period_date').annotate(
            count=Count('id')
        ).order_by('period_date')
        
        result = [{
            'date': item['period_date'],
            'servings': item['count'],
            'total_ml': item['count'] * self.SERVING_SIZE_ML
        } for item in stats]
        
        return Response(result)

class S3UploadUrlView(APIView):
    def get(self, request):
        s3_client = boto3.client('s3')
        bucket = os.getenv('AWS_S3_BUCKET')
        
        # Generate a unique file name
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        key = f'reviews/{request.user_id}/{timestamp}.jpg'
        
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
