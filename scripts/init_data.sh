#!/bin/bash

echo "Adding sample whiskey data to DynamoDB..."

# Whiskeys data
docker-compose exec -T localstack awslocal dynamodb put-item --table-name Whiskeys --item '{"id":{"S":"whiskey-1"},"name":{"S":"山崎12年"},"distillery":{"S":"サントリー山崎蒸溜所"},"created_at":{"S":"2024-01-01T00:00:00"},"updated_at":{"S":"2024-01-01T00:00:00"}}' --region ap-northeast-1 > /dev/null

docker-compose exec -T localstack awslocal dynamodb put-item --table-name Whiskeys --item '{"id":{"S":"whiskey-2"},"name":{"S":"白州12年"},"distillery":{"S":"サントリー白州蒸溜所"},"created_at":{"S":"2024-01-01T00:00:00"},"updated_at":{"S":"2024-01-01T00:00:00"}}' --region ap-northeast-1 > /dev/null

docker-compose exec -T localstack awslocal dynamodb put-item --table-name Whiskeys --item '{"id":{"S":"whiskey-3"},"name":{"S":"余市15年"},"distillery":{"S":"ニッカウヰスキー余市蒸溜所"},"created_at":{"S":"2024-01-01T00:00:00"},"updated_at":{"S":"2024-01-01T00:00:00"}}' --region ap-northeast-1 > /dev/null

docker-compose exec -T localstack awslocal dynamodb put-item --table-name Whiskeys --item '{"id":{"S":"whiskey-4"},"name":{"S":"響21年"},"distillery":{"S":"サントリー"},"created_at":{"S":"2024-01-01T00:00:00"},"updated_at":{"S":"2024-01-01T00:00:00"}}' --region ap-northeast-1 > /dev/null

docker-compose exec -T localstack awslocal dynamodb put-item --table-name Whiskeys --item '{"id":{"S":"whiskey-5"},"name":{"S":"宮城峡15年"},"distillery":{"S":"ニッカウヰスキー宮城峡蒸溜所"},"created_at":{"S":"2024-01-01T00:00:00"},"updated_at":{"S":"2024-01-01T00:00:00"}}' --region ap-northeast-1 > /dev/null

docker-compose exec -T localstack awslocal dynamodb put-item --table-name Whiskeys --item '{"id":{"S":"whiskey-6"},"name":{"S":"知多"},"distillery":{"S":"サントリー知多蒸溜所"},"created_at":{"S":"2024-01-01T00:00:00"},"updated_at":{"S":"2024-01-01T00:00:00"}}' --region ap-northeast-1 > /dev/null

docker-compose exec -T localstack awslocal dynamodb put-item --table-name Whiskeys --item '{"id":{"S":"whiskey-7"},"name":{"S":"竹鶴17年"},"distillery":{"S":"ニッカウヰスキー"},"created_at":{"S":"2024-01-01T00:00:00"},"updated_at":{"S":"2024-01-01T00:00:00"}}' --region ap-northeast-1 > /dev/null

docker-compose exec -T localstack awslocal dynamodb put-item --table-name Whiskeys --item '{"id":{"S":"whiskey-8"},"name":{"S":"富士山麓"},"distillery":{"S":"キリンディスティラリー富士御殿場蒸溜所"},"created_at":{"S":"2024-01-01T00:00:00"},"updated_at":{"S":"2024-01-01T00:00:00"}}' --region ap-northeast-1 > /dev/null

echo "Whiskeys data added."

echo "Adding sample reviews data..."

# Reviews data
docker-compose exec -T localstack awslocal dynamodb put-item --table-name Reviews --item '{"id":{"S":"review-1"},"whiskey_id":{"S":"whiskey-1"},"user_id":{"S":"test-user"},"notes":{"S":"非常に芳醇で複雑な味わい。シェリー樽の甘味とスモーキーな香りが絶妙にバランスしている。"},"rating":{"N":"5"},"serving_style":{"S":"NEAT"},"date":{"S":"2024-01-15"},"created_at":{"S":"2024-01-15T10:00:00"},"updated_at":{"S":"2024-01-15T10:00:00"}}' --region ap-northeast-1 > /dev/null

docker-compose exec -T localstack awslocal dynamodb put-item --table-name Reviews --item '{"id":{"S":"review-2"},"whiskey_id":{"S":"whiskey-2"},"user_id":{"S":"test-user"},"notes":{"S":"爽やかで清涼感のある味わい。森林のような香りと軽やかな口当たりが印象的。"},"rating":{"N":"4"},"serving_style":{"S":"ROCKS"},"date":{"S":"2024-01-20"},"created_at":{"S":"2024-01-20T15:00:00"},"updated_at":{"S":"2024-01-20T15:00:00"}}' --region ap-northeast-1 > /dev/null

docker-compose exec -T localstack awslocal dynamodb put-item --table-name Reviews --item '{"id":{"S":"review-3"},"whiskey_id":{"S":"whiskey-3"},"user_id":{"S":"test-user"},"notes":{"S":"ピートの効いたスモーキーな香りが特徴的。力強い味わいで余韻も長い。"},"rating":{"N":"4"},"serving_style":{"S":"NEAT"},"date":{"S":"2024-01-25"},"created_at":{"S":"2024-01-25T18:00:00"},"updated_at":{"S":"2024-01-25T18:00:00"}}' --region ap-northeast-1 > /dev/null

docker-compose exec -T localstack awslocal dynamodb put-item --table-name Reviews --item '{"id":{"S":"review-4"},"whiskey_id":{"S":"whiskey-4"},"user_id":{"S":"test-user"},"notes":{"S":"究極のバランス。日本ウィスキーの最高峰と呼ぶにふさわしい逸品。"},"rating":{"N":"5"},"serving_style":{"S":"NEAT"},"date":{"S":"2024-02-01"},"created_at":{"S":"2024-02-01T19:00:00"},"updated_at":{"S":"2024-02-01T19:00:00"}}' --region ap-northeast-1 > /dev/null

docker-compose exec -T localstack awslocal dynamodb put-item --table-name Reviews --item '{"id":{"S":"review-5"},"whiskey_id":{"S":"whiskey-5"},"user_id":{"S":"test-user"},"notes":{"S":"花やかで上品な香り。フルーティーで飲みやすい。"},"rating":{"N":"4"},"serving_style":{"S":"NEAT"},"date":{"S":"2024-02-05"},"created_at":{"S":"2024-02-05T20:00:00"},"updated_at":{"S":"2024-02-05T20:00:00"}}' --region ap-northeast-1 > /dev/null

docker-compose exec -T localstack awslocal dynamodb put-item --table-name Reviews --item '{"id":{"S":"review-6"},"whiskey_id":{"S":"whiskey-6"},"user_id":{"S":"test-user"},"notes":{"S":"軽やかでクリーン。ハイボールに最適な味わい。"},"rating":{"N":"3"},"serving_style":{"S":"HIGH_BALL"},"date":{"S":"2024-02-10"},"created_at":{"S":"2024-02-10T18:00:00"},"updated_at":{"S":"2024-02-10T18:00:00"}}' --region ap-northeast-1 > /dev/null

docker-compose exec -T localstack awslocal dynamodb put-item --table-name Reviews --item '{"id":{"S":"review-7"},"whiskey_id":{"S":"whiskey-7"},"user_id":{"S":"test-user"},"notes":{"S":"重厚で深い味わい。シェリー樽の甘みが印象的。"},"rating":{"N":"5"},"serving_style":{"S":"NEAT"},"date":{"S":"2024-02-15"},"created_at":{"S":"2024-02-15T21:00:00"},"updated_at":{"S":"2024-02-15T21:00:00"}}' --region ap-northeast-1 > /dev/null

docker-compose exec -T localstack awslocal dynamodb put-item --table-name Reviews --item '{"id":{"S":"review-8"},"whiskey_id":{"S":"whiskey-8"},"user_id":{"S":"test-user"},"notes":{"S":"まろやかで穏やか。初心者にもおすすめできる優しい味わい。"},"rating":{"N":"3"},"serving_style":{"S":"ROCKS"},"date":{"S":"2024-02-20"},"created_at":{"S":"2024-02-20T17:00:00"},"updated_at":{"S":"2024-02-20T17:00:00"}}' --region ap-northeast-1 > /dev/null

docker-compose exec -T localstack awslocal dynamodb put-item --table-name Reviews --item '{"id":{"S":"review-9"},"whiskey_id":{"S":"whiskey-4"},"user_id":{"S":"test-user-2"},"notes":{"S":"価格は高いが、それに見合う価値がある。特別な日に飲みたい。"},"rating":{"N":"4"},"serving_style":{"S":"NEAT"},"date":{"S":"2024-02-25"},"created_at":{"S":"2024-02-25T22:00:00"},"updated_at":{"S":"2024-02-25T22:00:00"}}' --region ap-northeast-1 > /dev/null

docker-compose exec -T localstack awslocal dynamodb put-item --table-name Reviews --item '{"id":{"S":"review-10"},"whiskey_id":{"S":"whiskey-1"},"user_id":{"S":"test-user-2"},"notes":{"S":"やはり山崎は別格。香りの複雑さが素晴らしい。"},"rating":{"N":"5"},"serving_style":{"S":"NEAT"},"date":{"S":"2024-03-01"},"created_at":{"S":"2024-03-01T19:30:00"},"updated_at":{"S":"2024-03-01T19:30:00"}}' --region ap-northeast-1 > /dev/null

echo "Reviews data added."
echo "Sample data initialization completed!"
echo ""
echo "Summary:"
echo "- 8 whiskeys added"
echo "- 10 reviews added"
echo ""
echo "You can now test the application at:"
echo "- Frontend: http://localhost:3000"
echo "- Backend API: http://localhost:8000/api/" 