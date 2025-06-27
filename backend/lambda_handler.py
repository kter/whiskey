"""
Lambda handler for Django API using Mangum
"""
import os
import django
from django.core.wsgi import get_wsgi_application
from mangum import Mangum

# Django setup for Lambda environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
django.setup()

# Get Django WSGI application
django_app = get_wsgi_application()

# Create Mangum handler
handler = Mangum(django_app, lifespan="off")

def lambda_handler(event, context):
    """
    AWS Lambda handler function
    """
    return handler(event, context)