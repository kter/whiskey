import os
import logging
from django.http import JsonResponse
from jose import jwt
from jose.exceptions import JWTError

logger = logging.getLogger(__name__)

class CognitoAuthMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.region = os.getenv('AWS_REGION', 'ap-northeast-1')
        self.user_pool_id = os.getenv('COGNITO_USER_POOL_ID')
        self.client_id = os.getenv('COGNITO_CLIENT_ID')
        self.jwks_url = f'https://cognito-idp.{self.region}.amazonaws.com/{self.user_pool_id}/.well-known/jwks.json'

    def __call__(self, request):
        logger.info(f"Auth middleware - Path: {request.path}, Method: {request.method}")
        
        # Skip authentication for non-API paths and OPTIONS requests
        if not request.path.startswith('/api/') or request.method == 'OPTIONS':
            logger.info(f"Skipping auth - non-API path or OPTIONS: {request.path}")
            return self.get_response(request)

        # Skip authentication for public endpoints
        public_endpoints = [
            '/api/whiskeys/suggest',
            '/api/whiskeys/ranking',
            '/api/reviews/public',
        ]
        if any(request.path.startswith(endpoint) for endpoint in public_endpoints):
            logger.info(f"Skipping auth - public endpoint: {request.path}")
            return self.get_response(request)

        # 開発環境用: ダミーのuser_idを設定
        environment = os.getenv('ENVIRONMENT', 'local')
        is_development = environment in ['local', 'dev', 'development']
        debug_mode = os.getenv('DJANGO_DEBUG', 'False').lower() == 'true'
        
        logger.info(f"Auth check - Environment: {environment}, is_development: {is_development}, debug_mode: {debug_mode}")
        
        if is_development or debug_mode:
            logger.info(f"Using development mode - assigning dummy user_id")
            request.user_id = 'development-user'
            return self.get_response(request)

        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return JsonResponse({'error': 'No valid authorization token provided'}, status=401)

        token = auth_header.split(' ')[1]
        try:
            # In production, you should cache the JWKS and validate token properly
            # This is a simplified version for development
            claims = jwt.get_unverified_claims(token)
            request.user_id = claims['sub']
            return self.get_response(request)
        except JWTError as e:
            return JsonResponse({'error': str(e)}, status=401) 