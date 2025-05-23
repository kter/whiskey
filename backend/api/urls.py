from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'reviews', views.ReviewViewSet, basename='review')

urlpatterns = [
    path('', include(router.urls)),
    path('whiskeys/suggest/', views.WhiskeySuggestView.as_view(), name='whiskey-suggest'),
    path('whiskeys/ranking/', views.WhiskeyRankingView.as_view(), name='whiskey-ranking'),
    path('s3/upload-url/', views.S3UploadUrlView.as_view(), name='s3-upload-url'),
] 