from rest_framework import serializers
from .models import Whiskey, Review

class WhiskeySerializer(serializers.ModelSerializer):
    avg_rating = serializers.FloatField(read_only=True, required=False)
    review_count = serializers.IntegerField(read_only=True, required=False)

    class Meta:
        model = Whiskey
        fields = ['id', 'name', 'distillery', 'avg_rating', 'review_count']

class ReviewSerializer(serializers.ModelSerializer):
    whiskey_name = serializers.CharField(source='whiskey.name', read_only=True)
    whiskey_distillery = serializers.CharField(source='whiskey.distillery', read_only=True)

    class Meta:
        model = Review
        fields = [
            'id', 'whiskey', 'whiskey_name', 'whiskey_distillery',
            'notes', 'rating', 'serving_style', 'date', 'image_url'
        ]
        read_only_fields = ['user_id']

    def create(self, validated_data):
        request = self.context.get('request')
        if request and hasattr(request, 'user_id'):
            validated_data['user_id'] = request.user_id
        return super().create(validated_data) 