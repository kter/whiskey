#!/bin/bash

# フロントエンドとバックエンドの連携テストスクリプト

set -e

echo "🧪 フロントエンドとバックエンドの連携テストを開始します..."

# 色の定義
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# テスト関数
test_endpoint() {
    local url=$1
    local description=$2
    local expected_status=${3:-200}
    
    echo -n "Testing $description... "
    
    status_code=$(curl -s -o /dev/null -w "%{http_code}" "$url" || echo "000")
    
    if [ "$status_code" == "$expected_status" ]; then
        echo -e "${GREEN}✓ OK (${status_code})${NC}"
        return 0
    else
        echo -e "${RED}✗ FAILED (${status_code})${NC}"
        return 1
    fi
}

echo ""
echo "📡 バックエンドAPI連携テスト"
echo "================================"

# バックエンドAPIエンドポイントテスト
test_endpoint "http://localhost:8000/api/whiskeys/ranking/" "ウィスキーランキング API"
test_endpoint "http://localhost:8000/api/whiskeys/suggest/?q=山崎" "ウィスキー検索 API"
test_endpoint "http://localhost:8000/api/reviews/public/" "パブリックレビュー API"

echo ""
echo "🌐 フロントエンドテスト"
echo "================================"

# フロントエンドアクセステスト
test_endpoint "http://localhost:3000" "フロントエンド トップページ"

echo ""
echo "⚙️  環境変数確認"
echo "================================"

# Docker Composeで設定された環境変数の確認
echo "📋 Frontend環境変数:"
docker-compose exec -T frontend printenv | grep NUXT_PUBLIC | sort

echo ""
echo "📋 Backend環境変数:"
docker-compose exec -T backend printenv | grep -E "(AWS_|COGNITO_|DJANGO_)" | sort

echo ""
echo "🔗 連携確認"
echo "================================"

# フロントエンドからバックエンドAPIを呼び出せるかテスト
echo "Testing frontend to backend connection..."

# Nuxt.jsアプリ内でAPIを呼び出すテスト
api_test_result=$(curl -s "http://localhost:3000" | grep -o "localhost:8000" || echo "not_found")

if [ "$api_test_result" != "not_found" ]; then
    echo -e "${GREEN}✓ フロントエンドの環境変数にバックエンドAPIが設定されています${NC}"
else
    echo -e "${YELLOW}⚠ フロントエンドの環境変数を確認してください${NC}"
fi

echo ""
echo "🎯 次のステップ"
echo "================================"
echo "1. 実際のAWS環境での動作確認:"
echo "   cd infra && ./scripts/deploy.sh dev"
echo ""
echo "2. Cognito認証の設定:"
echo "   - User Pool作成後の環境変数更新"
echo "   - フロントエンドでのサインイン/アップテスト"
echo ""
echo "3. S3画像アップロード機能のテスト:"
echo "   - プリサインドURL生成確認"
echo "   - 画像アップロード動作確認"

echo ""
echo -e "${GREEN}🎉 連携テスト完了！${NC}" 