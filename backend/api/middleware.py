import os
from django.http import JsonResponse
from jose import jwt
from jose.exceptions import JWTError

class CognitoAuthMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.region = os.getenv('AWS_REGION', 'ap-northeast-1')
        self.user_pool_id = os.getenv('COGNITO_USER_POOL_ID')
        self.client_id = os.getenv('COGNITO_CLIENT_ID')
        self.jwks_url = f'https://cognito-idp.{self.region}.amazonaws.com/{self.user_pool_id}/.well-known/jwks.json'

    def __call__(self, request):
        # Skip authentication for non-API paths and OPTIONS requests
        if not request.path.startswith('/api/') or request.method == 'OPTIONS':
            return self.get_response(request)

        # Skip authentication for public endpoints
        public_endpoints = [
            '/api/whiskeys/suggest',
            '/api/whiskeys/ranking',
        ]
        if any(request.path.startswith(endpoint) for endpoint in public_endpoints):
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