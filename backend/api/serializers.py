from rest_framework import serializers
from .models import Review, User

class WhiskeySerializer(serializers.Serializer):
    id = serializers.CharField(read_only=True)
    name = serializers.CharField(max_length=200)
    distillery = serializers.CharField(max_length=200)
    avg_rating = serializers.FloatField(read_only=True, required=False)
    review_count = serializers.IntegerField(read_only=True, required=False)
    created_at = serializers.CharField(read_only=True)
    updated_at = serializers.CharField(read_only=True)

class ReviewSerializer(serializers.Serializer):
    id = serializers.CharField(read_only=True)
    whiskey_id = serializers.CharField(required=False, read_only=True)  # レスポンス用
    whiskey = serializers.CharField(write_only=True)  # 作成時のみ使用
    whiskey_name = serializers.CharField(required=False, read_only=True)
    whiskey_distillery = serializers.CharField(required=False, read_only=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    rating = serializers.IntegerField(min_value=1, max_value=5)
    serving_style = serializers.ChoiceField(choices=Review.ServingStyle.CHOICES)
    date = serializers.DateField()
    image_url = serializers.URLField(required=False, allow_blank=True)
    created_at = serializers.CharField(read_only=True)
    updated_at = serializers.CharField(read_only=True)
    user_id = serializers.CharField(read_only=True)

    def validate_date(self, value):
        return value.isoformat() if hasattr(value, 'isoformat') else value

    def to_representation(self, instance):
        """DynamoDBのデータを適切な形式に変換"""
        if isinstance(instance, dict):
            # DynamoDBから取得したデータの場合
            ret = instance.copy()
            # whiskey_idをwhiskeyにマップ（フロントエンドとの互換性）
            if 'whiskey_id' in ret:
                ret['whiskey'] = ret['whiskey_id']
            return ret
        return super().to_representation(instance) 

class UserProfileSerializer(serializers.Serializer):
    user_id = serializers.CharField(read_only=True)
    nickname = serializers.CharField(max_length=50)
    display_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    created_at = serializers.CharField(read_only=True)
    updated_at = serializers.CharField(read_only=True)

    def validate_nickname(self, value):
        """ニックネームのバリデーション"""
        if not value or not value.strip():
            raise serializers.ValidationError("ニックネームは必須です")
        
        # 長すぎる場合
        if len(value.strip()) > 50:
            raise serializers.ValidationError("ニックネームは50文字以内で入力してください")
        
        # 不適切な文字が含まれている場合
        import re
        if not re.match(r'^[a-zA-Z0-9\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF\s_-]+$', value.strip()):
            raise serializers.ValidationError("ニックネームに使用できない文字が含まれています")
        
        return value.strip()