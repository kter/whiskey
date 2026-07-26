#!/usr/bin/env python3
"""
高信頼度ウイスキーデータをDynamoDBに投入
- 決定論的なcatalog_keyによる再投入
- 入力内および既存テーブルの重複検出
- 検索API互換フィールドを維持
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Set

import boto3


ROOT = Path(__file__).resolve().parents[1]
COMMON_PYTHON = ROOT / "lambda" / "common" / "python"
if str(COMMON_PYTHON) not in sys.path:
    sys.path.insert(0, str(COMMON_PYTHON))

from whiskey_common.normalize import normalize_text  # noqa: E402

from catalog.catalog import IDENTITY_FIELDS, catalog_key  # noqa: E402


DEV_ACCOUNT_ID = "031921999648"


def create_dynamodb_resource(target: str):
    """Create a verified DynamoDB resource for an explicit target."""
    if target == "local":
        session = boto3.Session(
            aws_access_key_id="local",
            aws_secret_access_key="local",
            region_name="ap-northeast-1",
        )
        return session.resource(
            "dynamodb",
            endpoint_url=os.environ.get("AWS_ENDPOINT_URL_DYNAMODB", "http://localhost:8000"),
        )

    profile = os.environ.get("AWS_PROFILE", "dev")
    session = boto3.Session(profile_name=profile, region_name="ap-northeast-1")
    identity = session.client("sts").get_caller_identity()
    if identity.get("Account") != DEV_ACCOUNT_ID:
        raise ValueError(
            f"dev target requires AWS account {DEV_ACCOUNT_ID}; got {identity.get('Account')}"
        )
    print(f"AWS account verified: {identity['Account']}")
    print(f"AWS ARN: {identity['Arn']}")
    return session.resource("dynamodb")


def bulk_write_whiskeys(table: Any, items: list[dict[str, Any]]) -> int:
    """Write items using the script-owned retrying DynamoDB batch writer."""
    with table.batch_writer(overwrite_by_pkeys=["id"]) as writer:
        for item in items:
            writer.put_item(Item=item)
    return len(items)


class WhiskeyDatabaseInserter:
    def __init__(self, target: str, dynamodb: Any | None = None):
        self.target = target
        self.dynamodb = dynamodb or create_dynamodb_resource(target)
        suffix = "local" if target == "local" else "dev"
        self.whiskey_table = self.dynamodb.Table(
            os.environ.get("WHISKEY_SEARCH_TABLE", f"WhiskeySearch-{suffix}")
        )
        self.processed_count = 0
        self.inserted_count = 0
        self.duplicate_count = 0
        
    def normalize_text(self, text: str) -> str:
        """テキストを検索用に正規化（DynamoDBサービスと同一）"""
        return normalize_text(text)

    def load_extraction_results(self, file_path: str) -> List[Dict]:
        """Bedrock抽出結果を読み込み"""
        print(f"抽出結果ファイル読み込み: {file_path}")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # ファイル形式を判定
        if 'results' in data:
            # Nova Pro/Claude Sonnet形式
            results = []
            for item in data['results']:
                extracted_whiskeys = item.get('extracted_whiskeys', [])
                for whiskey in extracted_whiskeys:
                    # Structured fields emitted by A2 are preserved as-is.
                    whiskey_data = dict(whiskey)
                    whiskey_data['rakuten_product_name'] = item.get('product_name', '')
                    results.append(whiskey_data)
            return results
        elif 'extraction_results' in data:
            # 旧形式
            results = []
            for item in data['extraction_results']:
                if item.get('is_whiskey', False):
                    result = {
                        'name': item.get('whiskey_name', ''),
                        'distillery': item.get('distillery', ''),
                        'confidence': item.get('confidence', 0.0),
                        'rakuten_product_name': item.get('original_name', ''),
                        'type': '',
                        'region': ''
                    }
                    results.append(result)
            return results
        else:
            raise ValueError(f"不明なファイル形式: {file_path}")

    def extract_all_whiskeys(self, results: List[Dict]) -> List[Dict]:
        """抽出結果からすべてのウイスキーを展開"""
        all_whiskeys = []
        
        for result in results:
            extracted_whiskeys = result.get('extracted_whiskeys', [])
            for whiskey in extracted_whiskeys:
                whiskey['rakuten_product_name'] = result.get('product_name', '')
                all_whiskeys.append(whiskey)
        
        print(f"抽出済みウイスキー総数: {len(all_whiskeys)}件")
        return all_whiskeys

    def remove_duplicates(self, whiskey_list: List[Dict]) -> List[Dict]:
        """重複除去（完全一致のみ除去、年数等のバリエーションは残す）"""
        seen_keys: Set[str] = set()
        unique_whiskeys = []
        
        for whiskey in whiskey_list:
            # None値のチェックを追加
            name = whiskey.get('name', '')
            if name is None:
                name = ''
            name = name.strip()
            
            distillery = whiskey.get('distillery', '')
            if distillery is None:
                distillery = ''
            distillery = distillery.strip()
            
            if not name:
                print(f"空のウイスキー名をスキップ: {whiskey}")
                continue
            
            # 重複チェック用キー（完全一致のみ）
            # 正規化はせず、元の名前をそのまま使用（大文字小文字のみ統一）
            duplicate_key = f"{name.lower()}#{distillery.lower()}"
            
            if duplicate_key not in seen_keys:
                seen_keys.add(duplicate_key)
                unique_whiskeys.append(whiskey)
            else:
                self.duplicate_count += 1
                print(f"重複除去: {name} - {distillery}")
        
        print(f"重複除去後: {len(unique_whiskeys)}件 (除去数: {self.duplicate_count})")
        return unique_whiskeys

    def validate_and_clean_data(self, whiskey_list: List[Dict]) -> List[Dict]:
        """データ検証と前処理クリーニング"""
        clean_whiskeys = []
        
        for i, whiskey in enumerate(whiskey_list):
            try:
                # None値のチェックを追加
                name = whiskey.get('name', '')
                if name is None:
                    name = ''
                name = name.strip()
                
                distillery = whiskey.get('distillery', '')
                if distillery is None:
                    distillery = ''
                distillery = distillery.strip()
                
                confidence = Decimal(str(whiskey.get('confidence', 0.0)))
                
                # 基本バリデーション
                if not name:
                    print(f"空のウイスキー名をスキップ: {whiskey}")
                    continue
                    
                # データクリーニング（DynamoDB GSI制約対応）
                # 空の蒸溜所名は"Unknown"に変換（GSIのキー制約により空文字列は不可）
                if not distillery:
                    distillery = "Unknown"
                    
                cleaned_whiskey = dict(whiskey)
                cleaned_whiskey.update(
                    {
                        'name': name,
                        'distillery': distillery,
                        'confidence': confidence,
                        'rakuten_product_name': whiskey.get('rakuten_product_name', ''),
                        'type': whiskey.get('type', ''),
                        'region': whiskey.get('region', ''),
                    }
                )
                
                clean_whiskeys.append(cleaned_whiskey)
                
            except Exception as e:
                print(f"データクリーニングエラー (インデックス {i}): {e}")
                print(f"問題のあるデータ: {whiskey}")
                continue
        
        print(f"データクリーニング後: {len(clean_whiskeys)}件")
        return clean_whiskeys

    def convert_to_db_format(self, whiskey_data: Dict) -> Dict:
        """DynamoDB投入用フォーマットに変換"""
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        # None値のチェックを追加
        name = whiskey_data.get('name', '')
        if name is None:
            name = ''
        name = name.strip()
        
        distillery = whiskey_data.get('distillery', '')
        if distillery is None:
            distillery = ''
        distillery = distillery.strip()

        name_ja = str(whiskey_data.get('name_ja') or name).strip()
        name_en = str(whiskey_data.get('name_en') or name).strip()
        canonical_name_ja = str(whiskey_data.get('canonical_name_ja') or name_ja).strip()
        canonical_name_en = str(whiskey_data.get('canonical_name_en') or name_en).strip()
        searchable_names = "|".join(dict.fromkeys(value for value in (name_ja, name_en) if value))
        identity = {
            "brand_key": whiskey_data.get("brand_key") or "unclassified",
            "expression_code": whiskey_data.get("expression_code") or name,
            "age": whiskey_data.get("age"),
            "edition": whiskey_data.get("edition"),
            "cask": whiskey_data.get("cask"),
            "vintage": whiskey_data.get("vintage"),
            "bottler": whiskey_data.get("bottler"),
        }
        entry_id = catalog_key(identity)

        item = {
            'id': entry_id,
            'catalog_key': entry_id,
            'catalog_schema_version': 2,
            'brand_key': identity['brand_key'],
            'expression_code': identity['expression_code'],
            'name': name,
            'name_ja': name_ja,
            'name_en': name_en,
            'canonical_name_ja': canonical_name_ja,
            'canonical_name_en': canonical_name_en,
            'distillery': distillery,
            'normalized_name': self.normalize_text(searchable_names),
            'normalized_distillery': self.normalize_text(distillery),
            'confidence': Decimal(str(whiskey_data.get('confidence', 0.0))),
            'source': 'rakuten_bedrock',
            'extraction_method': 'claude_sonnet_4',
            'rakuten_product_name': whiskey_data.get('rakuten_product_name', ''),
            'type': whiskey_data.get('type', ''),
            'region': whiskey_data.get('region', ''),
            'created_at': now,
            'updated_at': now
        }

        for field in IDENTITY_FIELDS[2:]:
            if identity[field] is not None:
                item[field] = identity[field]
        for field in (
            'brand_ja',
            'brand_en',
            'brand_aliases',
            'distillery_ja',
            'distillery_en',
            'country',
            'abv',
        ):
            if whiskey_data.get(field) is not None:
                item[field] = whiskey_data[field]
        return item

    def report_existing_duplicates(self) -> dict[str, list[list[dict[str, Any]]]]:
        """Scan the target table and report duplicate identities without modifying data."""
        records: list[dict[str, Any]] = []
        scan_kwargs: dict[str, Any] = {}
        while True:
            response = self.whiskey_table.scan(**scan_kwargs)
            records.extend(response.get("Items", []))
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
            scan_kwargs["ExclusiveStartKey"] = last_key

        reports: dict[str, list[list[dict[str, Any]]]] = {}
        for field in ("catalog_key", "normalized_name"):
            groups: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
            for record in records:
                value = record.get(field)
                if field == "normalized_name" and not value:
                    names = dict.fromkeys(
                        str(record.get(name_field) or "").strip()
                        for name_field in ("name", "name_ja", "name_en")
                    )
                    value = self.normalize_text("|".join(name for name in names if name))
                if value:
                    groups[str(value)].append(record)
            duplicates = [group for group in groups.values() if len(group) > 1]
            reports[field] = duplicates
            print(f"{field} duplicate groups: {len(duplicates)}")
            for group in duplicates:
                summary = [
                    {
                        "id": record.get("id"),
                        "name": record.get("name"),
                        field: record.get(field),
                    }
                    for record in group
                ]
                print(json.dumps(summary, ensure_ascii=False, default=str))
        return reports

    def insert_to_dynamodb(self, whiskey_list: List[Dict]) -> bool:
        """DynamoDBへの一括投入"""
        if not whiskey_list:
            print("投入するデータがありません")
            return True
        
        # フォーマット変換
        db_items = []
        for whiskey in whiskey_list:
            try:
                db_item = self.convert_to_db_format(whiskey)
                db_items.append(db_item)
            except Exception as e:
                print(f"フォーマット変換エラー: {e}")
                continue
        
        # DynamoDB投入
        print(f"DynamoDB投入開始: {len(db_items)}件")
        success_count = bulk_write_whiskeys(self.whiskey_table, db_items)

        self.inserted_count = success_count
        print(f"DynamoDB投入完了: {success_count}/{len(db_items)}件")
        
        return success_count == len(db_items)

    def process_file(self, input_file: str) -> Dict:
        """メイン処理フロー（重複排除をDB投入前に実行）"""
        print("=== ウイスキーデータDynamoDB投入開始 ===")
        print(f"設定: 前処理重複排除")  # confidence関連の記述を削除
        
        try:
            # 1. 抽出結果読み込み（すでに展開済み）
            all_whiskeys = self.load_extraction_results(input_file)
            print(f"読み込み完了: {len(all_whiskeys)}件のウイスキー")
            self.processed_count = len(all_whiskeys)
            
            # 3. データ検証とクリーニング
            clean_whiskeys = self.validate_and_clean_data(all_whiskeys)
            # self.low_confidence_count の計算を削除または修正
            # self.low_confidence_count = len(all_whiskeys) - len(clean_whiskeys)
            
            # 4. 重複除去（DB投入前）
            unique_whiskeys = self.remove_duplicates(clean_whiskeys)
            
            # 5. DynamoDB投入
            success = self.insert_to_dynamodb(unique_whiskeys)
            
            # 6. 統計情報
            stats = {
                'success': success,
                'processed_count': self.processed_count,
                'clean_count': len(clean_whiskeys),  # high_confidence_countをclean_countに変更
                'duplicates_removed': self.duplicate_count,
                'inserted_count': self.inserted_count,
                # 'confidence_threshold': self.confidence_threshold  # この行を削除
            }
            
            print("=== 処理完了 ===")
            print(f"総ウイスキー数: {stats['processed_count']}件")
            print(f"クリーニング後: {stats['clean_count']}件")  # 表示を変更
            print(f"重複除去: {stats['duplicates_removed']}件")
            print(f"DB投入: {stats['inserted_count']}件")
            print(f"最終成功率: {stats['inserted_count']}/{stats['clean_count']}")
            
            return stats
            
        except Exception as e:
            print(f"エラー: {e}")
            return {
                'success': False,
                'error': str(e),
                'processed_count': self.processed_count,
                'inserted_count': self.inserted_count
            }

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Insert extracted whiskeys into DynamoDB")
    parser.add_argument("input_file", nargs="?")
    parser.add_argument("--target", choices=("local", "dev"), required=True)
    parser.add_argument(
        "--report-duplicates",
        action="store_true",
        help="scan and report existing duplicate catalog keys and normalized names",
    )
    args = parser.parse_args(argv)
    if not args.input_file and not args.report_duplicates:
        parser.error("input_file is required unless --report-duplicates is specified")
    return args


def main(argv: list[str] | None = None) -> int:
    """メイン実行関数"""
    args = parse_args(argv)
    if args.input_file and not os.path.exists(args.input_file):
        print(f"ERROR: ファイルが見つかりません: {args.input_file}", file=sys.stderr)
        return 1
    try:
        inserter = WhiskeyDatabaseInserter(args.target)
        if args.report_duplicates:
            inserter.report_existing_duplicates()
        if not args.input_file:
            return 0
        result = inserter.process_file(args.input_file)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if not result["success"]:
        print("ERROR: 処理に失敗しました", file=sys.stderr)
        return 1
    print("SUCCESS: DynamoDB投入が正常に完了しました")
    return 0


if __name__ == "__main__":
    sys.exit(main())
