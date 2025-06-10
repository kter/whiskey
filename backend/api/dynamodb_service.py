import boto3
import os
import uuid
from datetime import datetime, date
from decimal import Decimal
from typing import Dict, List, Optional, Any
from boto3.dynamodb.conditions import Key, Attr
import time


class DynamoDBService:
    def __init__(self):
        self.region = os.getenv('AWS_REGION', 'ap-northeast-1')
        endpoint_url = os.getenv('AWS_ENDPOINT_URL')
        
        # 環境に応じたテーブル名を設定
        environment = os.getenv('ENVIRONMENT', 'dev')
        self.whiskey_table_name = f'Whiskeys-{environment}'
        self.review_table_name = f'Reviews-{environment}'
        self.user_table_name = f'Users-{environment}'
        
        if endpoint_url:
            # LocalStack環境
            self.dynamodb = boto3.resource(
                'dynamodb',
                region_name=self.region,
                endpoint_url=endpoint_url,
                aws_access_key_id='dummy',
                aws_secret_access_key='dummy'
            )
        else:
            # 本番環境
            self.dynamodb = boto3.resource('dynamodb', region_name=self.region)
        
        # テーブル参照の初期化（遅延読み込み）
        self._whiskey_table = None
        self._review_table = None
        self._user_table = None
    
    @property
    def whiskey_table(self):
        if self._whiskey_table is None:
            try:
                self._whiskey_table = self.dynamodb.Table(self.whiskey_table_name)
                # テーブルの存在確認
                self._whiskey_table.load()
            except Exception as e:
                print(f"Whiskeys table {self.whiskey_table_name} not found, creating: {e}")
                self._create_whiskey_table()
                # 作成後に少し待機
                time.sleep(2)
                self._whiskey_table = self.dynamodb.Table(self.whiskey_table_name)
        return self._whiskey_table
    
    @property
    def review_table(self):
        if self._review_table is None:
            try:
                self._review_table = self.dynamodb.Table(self.review_table_name)
                # テーブルの存在確認
                self._review_table.load()
            except Exception as e:
                print(f"Reviews table {self.review_table_name} not found, creating: {e}")
                self._create_review_table()
                # 作成後に少し待機
                time.sleep(2)
                self._review_table = self.dynamodb.Table(self.review_table_name)
        return self._review_table
    
    @property
    def user_table(self):
        if self._user_table is None:
            try:
                self._user_table = self.dynamodb.Table(self.user_table_name)
                # テーブルの存在確認
                self._user_table.load()
            except Exception as e:
                print(f"Users table {self.user_table_name} not found, creating: {e}")
                self._create_user_table()
                # 作成後に少し待機
                time.sleep(2)
                self._user_table = self.dynamodb.Table(self.user_table_name)
        return self._user_table
    
    def _create_whiskey_table(self):
        """Whiskeysテーブルを作成"""
        try:
            table = self.dynamodb.create_table(
                TableName=self.whiskey_table_name,
                KeySchema=[
                    {'AttributeName': 'id', 'KeyType': 'HASH'}
                ],
                AttributeDefinitions=[
                    {'AttributeName': 'id', 'AttributeType': 'S'},
                    {'AttributeName': 'name', 'AttributeType': 'S'}
                ],
                GlobalSecondaryIndexes=[
                    {
                        'IndexName': 'NameIndex',
                        'KeySchema': [
                            {'AttributeName': 'name', 'KeyType': 'HASH'}
                        ],
                        'Projection': {'ProjectionType': 'ALL'},
                        'BillingMode': 'PAY_PER_REQUEST'
                    }
                ],
                BillingMode='PAY_PER_REQUEST'
            )
            print("Created Whiskeys table")
            return table
        except Exception as e:
            print(f"Error creating Whiskeys table: {e}")
            return None
    
    def _create_review_table(self):
        """Reviewsテーブルを作成"""
        try:
            table = self.dynamodb.create_table(
                TableName=self.review_table_name,
                KeySchema=[
                    {'AttributeName': 'id', 'KeyType': 'HASH'}
                ],
                AttributeDefinitions=[
                    {'AttributeName': 'id', 'AttributeType': 'S'},
                    {'AttributeName': 'user_id', 'AttributeType': 'S'},
                    {'AttributeName': 'date', 'AttributeType': 'S'}
                ],
                GlobalSecondaryIndexes=[
                    {
                        'IndexName': 'UserDateIndex',
                        'KeySchema': [
                            {'AttributeName': 'user_id', 'KeyType': 'HASH'},
                            {'AttributeName': 'date', 'KeyType': 'RANGE'}
                        ],
                        'Projection': {'ProjectionType': 'ALL'},
                        'BillingMode': 'PAY_PER_REQUEST'
                    }
                ],
                BillingMode='PAY_PER_REQUEST'
            )
            print("Created Reviews table")
            return table
        except Exception as e:
            print(f"Error creating Reviews table: {e}")
            return None
    
    def _create_user_table(self):
        """Usersテーブルを作成"""
        try:
            table = self.dynamodb.create_table(
                TableName=self.user_table_name,
                KeySchema=[
                    {'AttributeName': 'user_id', 'KeyType': 'HASH'}
                ],
                AttributeDefinitions=[
                    {'AttributeName': 'user_id', 'AttributeType': 'S'}
                ],
                BillingMode='PAY_PER_REQUEST'
            )
            print("Created Users table")
            return table
        except Exception as e:
            print(f"Error creating Users table: {e}")
            return None

    def _serialize_item(self, item: Dict) -> Dict:
        """Decimal型を適切な型に変換"""
        if isinstance(item, dict):
            return {k: self._serialize_item(v) for k, v in item.items()}
        elif isinstance(item, list):
            return [self._serialize_item(v) for v in item]
        elif isinstance(item, Decimal):
            return float(item) if item % 1 else int(item)
        else:
            return item

    # Whiskey operations
    def create_whiskey(self, name: str, distillery: str) -> Dict:
        """ウィスキーを作成"""
        whiskey_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        
        item = {
            'id': whiskey_id,
            'name': name,
            'distillery': distillery,
            'created_at': now,
            'updated_at': now
        }
        
        try:
            self.whiskey_table.put_item(Item=item)
            return self._serialize_item(item)
        except Exception as e:
            print(f"Error creating whiskey: {e}")
            raise
    
    def get_whiskey(self, whiskey_id: str) -> Optional[Dict]:
        """ウィスキーを取得"""
        try:
            response = self.whiskey_table.get_item(Key={'id': whiskey_id})
            return self._serialize_item(response.get('Item')) if 'Item' in response else None
        except Exception as e:
            print(f"Error getting whiskey {whiskey_id}: {e}")
            return None
    
    def search_whiskeys(self, query: str, limit: int = 10) -> List[Dict]:
        """ウィスキーを名前で検索"""
        try:
            response = self.whiskey_table.scan(
                FilterExpression=Attr('name').contains(query),
                Limit=limit
            )
            return [self._serialize_item(item) for item in response['Items']]
        except Exception as e:
            print(f"Error searching whiskeys: {e}")
            return []
    
    def get_whiskey_ranking(self, limit: int = 10) -> List[Dict]:
        """レビューの平均評価でウィスキーランキングを取得"""
        try:
            # すべてのレビューを取得してウィスキーごとに集計
            reviews = self.review_table.scan()['Items']
            
            whiskey_stats = {}
            for review in reviews:
                whiskey_id = review['whiskey_id']
                rating = float(review['rating'])
                
                if whiskey_id not in whiskey_stats:
                    whiskey_stats[whiskey_id] = {'total_rating': 0, 'count': 0}
                
                whiskey_stats[whiskey_id]['total_rating'] += rating
                whiskey_stats[whiskey_id]['count'] += 1
            
            # 平均評価を計算
            ranked_whiskeys = []
            for whiskey_id, stats in whiskey_stats.items():
                avg_rating = stats['total_rating'] / stats['count']
                whiskey = self.get_whiskey(whiskey_id)
                if whiskey:
                    whiskey['avg_rating'] = avg_rating
                    whiskey['review_count'] = stats['count']
                    ranked_whiskeys.append(whiskey)
            
            # 平均評価でソート
            ranked_whiskeys.sort(key=lambda x: x['avg_rating'], reverse=True)
            return ranked_whiskeys[:limit]
        except Exception as e:
            print(f"Error getting whiskey ranking: {e}")
            return []

    # Review operations
    def create_review(self, whiskey_id: str, user_id: str, notes: str, 
                     rating: int, serving_style: str, review_date: str, 
                     image_url: str = None) -> Dict:
        """レビューを作成"""
        review_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        
        item = {
            'id': review_id,
            'whiskey_id': whiskey_id,
            'user_id': user_id,
            'notes': notes,
            'rating': rating,
            'serving_style': serving_style,
            'date': review_date,
            'created_at': now,
            'updated_at': now
        }
        
        if image_url:
            item['image_url'] = image_url
        
        try:
            self.review_table.put_item(Item=item)
            return self._serialize_item(item)
        except Exception as e:
            print(f"Error creating review: {e}")
            raise
    
    def get_review(self, review_id: str) -> Optional[Dict]:
        """レビューを取得"""
        try:
            response = self.review_table.get_item(Key={'id': review_id})
            return self._serialize_item(response.get('Item')) if 'Item' in response else None
        except Exception as e:
            print(f"Error getting review {review_id}: {e}")
            return None
    
    def update_review(self, review_id: str, updates: Dict) -> Optional[Dict]:
        """レビューを更新"""
        updates['updated_at'] = datetime.now().isoformat()
        
        update_expression = "SET "
        expression_values = {}
        
        for key, value in updates.items():
            update_expression += f"{key} = :{key}, "
            expression_values[f":{key}"] = value
        
        update_expression = update_expression.rstrip(", ")
        
        try:
            response = self.review_table.update_item(
                Key={'id': review_id},
                UpdateExpression=update_expression,
                ExpressionAttributeValues=expression_values,
                ReturnValues='ALL_NEW'
            )
            
            return self._serialize_item(response.get('Attributes'))
        except Exception as e:
            print(f"Error updating review {review_id}: {e}")
            return None
    
    def delete_review(self, review_id: str) -> bool:
        """レビューを削除"""
        try:
            self.review_table.delete_item(Key={'id': review_id})
            return True
        except Exception as e:
            print(f"Error deleting review {review_id}: {e}")
            return False
    
    def get_user_reviews(self, user_id: str, page: int = 1, per_page: int = 10) -> Dict:
        """ユーザーのレビューを取得（ページネーション付き）"""
        try:
            response = self.review_table.query(
                IndexName='UserDateIndex',
                KeyConditionExpression=Key('user_id').eq(user_id),
                ScanIndexForward=False,  # 新しい順
                Limit=per_page * 2  # 多めに取得してページネーションを実装
            )
            
            items = [self._serialize_item(item) for item in response['Items']]
            
            # 簡易的なページネーション
            start_index = (page - 1) * per_page
            end_index = start_index + per_page
            page_items = items[start_index:end_index]
            
            return {
                'results': page_items,
                'count': len(items),
                'next': f"?page={page + 1}" if end_index < len(items) else None,
                'previous': f"?page={page - 1}" if page > 1 else None
            }
        except Exception as e:
            print(f"Error getting user reviews: {e}")
            return {
                'results': [],
                'count': 0,
                'next': None,
                'previous': None
            }

    def get_all_reviews(self, page: int = 1, per_page: int = 10) -> Dict:
        """全てのレビューを取得（ページネーション付き、認証不要）"""
        try:
            response = self.review_table.scan()
            items = [self._serialize_item(item) for item in response['Items']]
            
            # 日付でソート（新しい順）
            items.sort(key=lambda x: x.get('date', ''), reverse=True)
            
            # 簡易的なページネーション
            start_index = (page - 1) * per_page
            end_index = start_index + per_page
            page_items = items[start_index:end_index]
            total_count = len(items)
            
            return {
                'results': page_items,
                'count': total_count,
                'next': f"?page={page + 1}" if end_index < total_count else None,
                'previous': f"?page={page - 1}" if page > 1 else None
            }
        except Exception as e:
            print(f"Error getting all reviews: {e}")
            return {
                'results': [],
                'count': 0,
                'next': None,
                'previous': None
            } 

    # User operations
    def get_user_profile(self, user_id: str) -> Optional[Dict]:
        """ユーザープロフィールを取得"""
        try:
            response = self.user_table.get_item(Key={'user_id': user_id})
            if 'Item' in response:
                return self._serialize_item(response['Item'])
            return None
        except Exception as e:
            print(f"Error getting user profile: {e}")
            return None

    def create_user_profile(self, user_id: str, nickname: str, display_name: Optional[str] = None) -> Dict:
        """ユーザープロフィールを作成"""
        now = datetime.now().isoformat()
        
        item = {
            'user_id': user_id,
            'nickname': nickname,
            'display_name': display_name,
            'created_at': now,
            'updated_at': now
        }
        
        try:
            # 既存のプロフィールが存在しないことを確認
            existing = self.get_user_profile(user_id)
            if existing:
                raise ValueError("User profile already exists")
            
            self.user_table.put_item(Item=item)
            return self._serialize_item(item)
        except Exception as e:
            print(f"Error creating user profile: {e}")
            raise

    def update_user_profile(self, user_id: str, nickname: Optional[str] = None, display_name: Optional[str] = None) -> Dict:
        """ユーザープロフィールを更新"""
        try:
            # 既存のプロフィールを確認
            existing = self.get_user_profile(user_id)
            if not existing:
                raise ValueError("User profile not found")
            
            # 更新するフィールドを準備
            update_expression = "SET updated_at = :updated_at"
            expression_values = {
                ':updated_at': datetime.now().isoformat()
            }
            
            if nickname is not None:
                update_expression += ", nickname = :nickname"
                expression_values[':nickname'] = nickname
            
            if display_name is not None:
                update_expression += ", display_name = :display_name"
                expression_values[':display_name'] = display_name
            
            response = self.user_table.update_item(
                Key={'user_id': user_id},
                UpdateExpression=update_expression,
                ExpressionAttributeValues=expression_values,
                ReturnValues='ALL_NEW'
            )
            
            return self._serialize_item(response['Attributes'])
        except Exception as e:
            print(f"Error updating user profile: {e}")
            raise

    def get_or_create_user_profile(self, user_id: str, default_nickname: str) -> Dict:
        """ユーザープロフィールを取得、存在しない場合は作成"""
        try:
            # 既存のプロフィールを確認
            profile = self.get_user_profile(user_id)
            if profile:
                return profile
            
            # プロフィールが存在しない場合は作成
            return self.create_user_profile(user_id, default_nickname)
        except Exception as e:
            print(f"Error getting or creating user profile: {e}")
            raise