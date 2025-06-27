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
        self.whiskey_search_table_name = f'WhiskeySearch-{environment}'
        
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
        self._whiskey_search_table = None
    
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
    
    @property
    def whiskey_search_table(self):
        if self._whiskey_search_table is None:
            try:
                self._whiskey_search_table = self.dynamodb.Table(self.whiskey_search_table_name)
                # テーブルの存在確認
                self._whiskey_search_table.load()
            except Exception as e:
                print(f"WhiskeySearch table {self.whiskey_search_table_name} not found, creating: {e}")
                self._create_whiskey_search_table()
                # 作成後に少し待機
                time.sleep(2)
                self._whiskey_search_table = self.dynamodb.Table(self.whiskey_search_table_name)
        return self._whiskey_search_table
    
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

    def _create_whiskey_search_table(self):
        """WhiskeySearchテーブルを作成 - 検索最適化用"""
        try:
            table = self.dynamodb.create_table(
                TableName=self.whiskey_search_table_name,
                KeySchema=[
                    {'AttributeName': 'id', 'KeyType': 'HASH'}
                ],
                AttributeDefinitions=[
                    {'AttributeName': 'id', 'AttributeType': 'S'},
                    {'AttributeName': 'normalized_name_ja', 'AttributeType': 'S'},
                    {'AttributeName': 'normalized_distillery_ja', 'AttributeType': 'S'},
                    {'AttributeName': 'normalized_name_en', 'AttributeType': 'S'},
                    {'AttributeName': 'normalized_distillery_en', 'AttributeType': 'S'}
                ],
                GlobalSecondaryIndexes=[
                    {
                        'IndexName': 'NameJaIndex',
                        'KeySchema': [
                            {'AttributeName': 'normalized_name_ja', 'KeyType': 'HASH'}
                        ],
                        'Projection': {'ProjectionType': 'ALL'},
                        'BillingMode': 'PAY_PER_REQUEST'
                    },
                    {
                        'IndexName': 'DistilleryJaIndex', 
                        'KeySchema': [
                            {'AttributeName': 'normalized_distillery_ja', 'KeyType': 'HASH'}
                        ],
                        'Projection': {'ProjectionType': 'ALL'},
                        'BillingMode': 'PAY_PER_REQUEST'
                    },
                    {
                        'IndexName': 'NameEnIndex',
                        'KeySchema': [
                            {'AttributeName': 'normalized_name_en', 'KeyType': 'HASH'}
                        ],
                        'Projection': {'ProjectionType': 'ALL'},
                        'BillingMode': 'PAY_PER_REQUEST'
                    },
                    {
                        'IndexName': 'DistilleryEnIndex',
                        'KeySchema': [
                            {'AttributeName': 'normalized_distillery_en', 'KeyType': 'HASH'}
                        ],
                        'Projection': {'ProjectionType': 'ALL'},
                        'BillingMode': 'PAY_PER_REQUEST'
                    }
                ],
                BillingMode='PAY_PER_REQUEST'
            )
            print("Created WhiskeySearch table")
            return table
        except Exception as e:
            print(f"Error creating WhiskeySearch table: {e}")
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

    # WhiskeySearch operations
    def create_whiskey_search_entry(self, whiskey_data: Dict) -> Dict:
        """検索用ウィスキーエントリを作成"""
        import uuid
        from datetime import datetime
        
        entry_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        
        item = {
            'id': entry_id,
            'name_en': whiskey_data.get('name', ''),
            'distillery_en': whiskey_data.get('distillery', ''),
            'name_ja': whiskey_data.get('name_ja', ''),
            'distillery_ja': whiskey_data.get('distillery_ja', ''),
            'normalized_name_en': self._normalize_text(whiskey_data.get('name', '')),
            'normalized_distillery_en': self._normalize_text(whiskey_data.get('distillery', '')),
            'normalized_name_ja': self._normalize_text(whiskey_data.get('name_ja', '')),
            'normalized_distillery_ja': self._normalize_text(whiskey_data.get('distillery_ja', '')),
            'description': whiskey_data.get('description', ''),
            'region': whiskey_data.get('region', ''),
            'type': whiskey_data.get('type', ''),
            'created_at': now,
            'updated_at': now
        }
        
        try:
            self.whiskey_search_table.put_item(Item=item)
            return self._serialize_item(item)
        except Exception as e:
            print(f"Error creating whiskey search entry: {e}")
            raise

    def search_whiskey_suggestions(self, query: str, limit: int = 10) -> List[Dict]:
        """日本語クエリでウィスキー検索を行う"""
        if not query or len(query) < 1:
            return []
        
        normalized_query = self._normalize_text(query)
        results = []
        
        try:
            # 日本語名で検索
            if normalized_query:
                response = self.whiskey_search_table.query(
                    IndexName='NameJaIndex',
                    KeyConditionExpression=Key('normalized_name_ja').eq(normalized_query),
                    Limit=limit
                )
                results.extend(response.get('Items', []))
            
            # 蒸留所名でも検索
            if len(results) < limit and normalized_query:
                response = self.whiskey_search_table.query(
                    IndexName='DistilleryJaIndex',
                    KeyConditionExpression=Key('normalized_distillery_ja').eq(normalized_query),
                    Limit=limit - len(results)
                )
                results.extend(response.get('Items', []))
            
            # 部分一致検索 (scanを使用、パフォーマンスに注意)
            if len(results) < limit:
                response = self.whiskey_search_table.scan(
                    FilterExpression=Attr('name_ja').contains(query) | Attr('distillery_ja').contains(query),
                    Limit=limit - len(results)
                )
                results.extend(response.get('Items', []))
            
            # 重複除去
            seen_ids = set()
            unique_results = []
            for item in results:
                if item['id'] not in seen_ids:
                    seen_ids.add(item['id'])
                    unique_results.append(self._serialize_item(item))
            
            return unique_results[:limit]
        except Exception as e:
            print(f"Error searching whiskey suggestions: {e}")
            return []

    def _normalize_text(self, text: str) -> str:
        """テキストを検索用に正規化"""
        if not text:
            return ''
        
        # 小文字に変換、スペースを除去
        normalized = text.lower().replace(' ', '').replace('　', '')
        
        # カタカナをひらがなに変換（簡易版）
        katakana_to_hiragana = str.maketrans(
            'アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲン',
            'あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをん'
        )
        normalized = normalized.translate(katakana_to_hiragana)
        
        return normalized

    def bulk_insert_whiskey_search_data(self, whiskey_list: List[Dict]) -> int:
        """ウィスキー検索データを一括挿入"""
        success_count = 0
        
        for whiskey_data in whiskey_list:
            try:
                self.create_whiskey_search_entry(whiskey_data)
                success_count += 1
            except Exception as e:
                print(f"Failed to insert whiskey search entry: {e}")
                continue
        
        print(f"Successfully inserted {success_count}/{len(whiskey_list)} whiskey search entries")
        return success_count