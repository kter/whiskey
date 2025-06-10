from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'reviews', views.ReviewViewSet, basename='review')
router.register(r'users', views.UserProfileViewSet, basename='user')

urlpatterns = [
    path('reviews/public/', views.PublicReviewsView.as_view(), name='public-reviews'),
    path('whiskeys/suggest/', views.WhiskeySuggestView.as_view(), name='whiskey-suggest'),
    path('whiskeys/ranking/', views.WhiskeyRankingView.as_view(), name='whiskey-ranking'),
    path('s3/upload-url/', views.S3UploadUrlView.as_view(), name='s3-upload-url'),
    path('users/profile/get-or-create/', views.UserProfileViewSet.as_view({'post': 'get_or_create_profile'}), name='user-profile-get-or-create'),
    path('', include(router.urls)),
] 