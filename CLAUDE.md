# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Architecture Overview

This is a **full-stack whiskey tasting review application** with serverless AWS architecture:

- **Frontend**: Nuxt.js 3 SPA with AWS Amplify (Cognito) authentication
- **Backend**: Django REST API running on ECS Fargate
- **Database**: DynamoDB with GSI indexes
- **Storage**: S3 for images with presigned URLs
- **Infrastructure**: AWS CDK (TypeScript)
- **Deployment**: GitHub Actions with environment-based auto-deploy

## Development Commands

### Local Development
```bash
# Start all services (includes LocalStack for AWS services)
make up
# or ./dev.sh up

# Stop services
make down

# View logs
make logs

# Backend shell access
make shell

# Run backend tests
make test

# Initialize test data
make init-db
```

### Frontend Development
```bash
cd frontend
npm run dev          # Development server at localhost:3000
npm run build        # Production build
npm run generate     # Static site generation
npm run lint         # ESLint
npm run lint:fix     # Auto-fix lint issues
```

### Backend Development
```bash
cd backend
python manage.py runserver              # Development server
python manage.py create_test_data       # Create sample data
pytest                                  # Run tests
```

### Infrastructure & Deployment
```bash
cd infra
npm run deploy:dev      # Deploy to dev environment
npm run deploy:prod     # Deploy to prod environment
npm run diff:dev        # Show deployment diff
npm run test            # Run infrastructure tests

# Manual deployment scripts
./scripts/deploy.sh dev     # Frontend deployment
./scripts/deploy-api.sh dev # Backend deployment
```

## Key Architecture Patterns

### Authentication Flow
1. AWS Cognito User Pool manages authentication
2. Amplify SDK handles frontend auth state with automatic token refresh
3. Backend validates JWT tokens via custom middleware (`CognitoAuthMiddleware`)
4. User ID extracted from JWT `sub` claim for data isolation

### Database Design (DynamoDB)
- **Whiskeys Table**: `id` (PK), with `NameIndex` GSI on `name`
- **Reviews Table**: `id` (PK), with `UserDateIndex` GSI on `user_id` + `date`
- All user data is isolated by `user_id` from JWT token

### API Structure
- RESTful endpoints under `/api/`
- Authentication required for CRUD operations
- Public read-only endpoints for rankings and discovery
- S3 presigned URLs for image uploads via `/api/s3/upload-url/`

### Frontend Composables
- `useAuth.ts`: Authentication state management
- `useWhiskeys.ts`: Whiskey search and suggestions
- `useSuggestWhiskeys.ts`: Autocomplete functionality

### Environment Management
- **local**: Docker Compose with LocalStack
- **dev**: AWS development (auto-deploy from `main` branch)
- **prod**: AWS production (auto-deploy from `production` branch)

## Important Files & Locations

### Core Backend Logic
- `backend/api/dynamodb_service.py`: All DynamoDB operations
- `backend/api/views.py`: API endpoints and business logic
- `backend/api/middleware.py`: JWT authentication middleware
- `backend/backend/settings.py`: Django configuration

### Core Frontend Logic
- `frontend/composables/useAuth.ts`: Authentication management
- `frontend/types/whiskey.ts`: TypeScript type definitions
- `frontend/plugins/amplify.client.ts`: Amplify configuration

### Configuration
- `frontend/nuxt.config.ts`: Frontend build and runtime config
- `docker-compose.yml`: Local development environment
- `infra/config/environments.ts`: Environment-specific AWS settings

### Data Models
```typescript
// Whiskey type
interface Whiskey {
  id: string;
  name: string;
  distillery: string;
  created_at: string;
  updated_at: string;
}

// Review type
interface Review {
  id: string;
  whiskey_id: string;
  user_id: string;
  rating: number;           // 1-5
  notes: string;
  serving_style: 'NEAT' | 'ROCKS' | 'WATER' | 'HIGHBALL';
  date: string;            // YYYY-MM-DD format
  image_url?: string;
  created_at: string;
  updated_at: string;
}
```

## Development Workflows

### Adding New API Endpoints
1. Add URL pattern to `backend/api/urls.py`
2. Implement view in `backend/api/views.py`
3. Add DynamoDB operations to `backend/api/dynamodb_service.py` if needed
4. Update frontend composables in `frontend/composables/`
5. Run `make test` for backend tests

### Modifying Database Schema
- DynamoDB is schemaless, but update TypeScript types in `frontend/types/whiskey.ts`
- Update serializers in `backend/api/serializers.py`
- Consider GSI requirements for new query patterns

### Frontend Component Development
- Follow existing patterns in `frontend/pages/` and `frontend/components/`
- Use Tailwind CSS for styling (already configured)
- Implement responsive design patterns
- Use composition API with TypeScript

### Deployment Process
- **Automatic**: Push to `main` (dev) or `production` (prod) branches
- **Manual**: Use deployment scripts in `scripts/` directory
- Infrastructure changes: Use CDK in `infra/` directory
- Always test locally with `make up` before deployment

## Environment Variables

### Required for Frontend
```bash
NUXT_PUBLIC_API_BASE_URL         # Backend API URL
NUXT_PUBLIC_USER_POOL_ID         # Cognito User Pool ID
NUXT_PUBLIC_USER_POOL_CLIENT_ID  # Cognito Client ID
NUXT_PUBLIC_REGION               # AWS Region
NUXT_PUBLIC_IMAGES_BUCKET        # S3 bucket for images
NUXT_PUBLIC_ENVIRONMENT          # Environment name
```

### Required for Backend
```bash
ENVIRONMENT                      # Environment name
DJANGO_SECRET_KEY               # Django secret
AWS_REGION                      # AWS Region
DYNAMODB_WHISKEYS_TABLE         # DynamoDB table name
DYNAMODB_REVIEWS_TABLE          # DynamoDB table name
S3_IMAGES_BUCKET               # S3 bucket name
COGNITO_USER_POOL_ID           # For JWT validation
```

## AWS Profile Configuration

**IMPORTANT**: When executing AWS CLI commands, always use the appropriate profile and set PAGER=cat:

### Development Environment
```bash
PAGER=cat AWS_PROFILE=dev aws [command]
```

### Production Environment  
```bash
PAGER=cat AWS_PROFILE=prd aws [command]
```

Examples:
```bash
# Check ECS logs (dev environment)
PAGER=cat AWS_PROFILE=dev aws logs tail /ecs/whiskey-api-dev --follow

# Check ECS logs (production environment)
PAGER=cat AWS_PROFILE=prd aws logs tail /ecs/whiskey-api-prod --follow

# List DynamoDB tables (dev environment)
PAGER=cat AWS_PROFILE=dev aws dynamodb list-tables

# Deploy infrastructure (automatically uses correct profile via scripts)
cd infra && npm run deploy:dev    # Uses dev profile internally
cd infra && npm run deploy:prod   # Uses prd profile internally
```

## Testing & Quality

### Running Tests
```bash
make test                    # Backend tests with pytest
cd infra && npm run test     # Infrastructure tests with Jest
cd frontend && npm run lint  # Frontend linting
```

### Local Services
When running `make up`, these services are available:
- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- LocalStack (AWS services): http://localhost:4566

## Troubleshooting

### Common Issues
1. **ECS deployment failures**: Check `./deploy-fix.sh` for ECR permission fixes
2. **Authentication errors**: Verify Cognito configuration and JWT token validity
3. **DynamoDB errors**: Ensure proper table names and GSI usage
4. **CORS issues**: Check allowed origins in Django settings

### Debug Commands
```bash
# Check ECS logs (with appropriate profile and pager)
PAGER=cat AWS_PROFILE=dev aws logs tail /ecs/whiskey-api-dev --follow
PAGER=cat AWS_PROFILE=prd aws logs tail /ecs/whiskey-api-prod --follow

# Health check
curl https://api.dev.whiskeybar.site/health/
curl https://api.whiskeybar.site/health/

# Local DynamoDB (via LocalStack - no profile needed)
PAGER=cat aws --endpoint-url=http://localhost:4566 dynamodb list-tables

# Check target group health (with appropriate profile and pager)
PAGER=cat AWS_PROFILE=dev aws elbv2 describe-target-health --target-group-arn <target-group-arn>

# CloudFormation stack events (with appropriate profile and pager)
PAGER=cat AWS_PROFILE=dev aws cloudformation describe-stack-events --stack-name WhiskeyApp-Dev
PAGER=cat AWS_PROFILE=prd aws cloudformation describe-stack-events --stack-name WhiskeyApp-Prod

# ECS service status (with appropriate profile and pager)
PAGER=cat AWS_PROFILE=dev aws ecs describe-services --cluster whiskey-api-cluster-dev --services whiskey-api-service-dev
```

Always run lint/typecheck commands after making changes, and test locally with Docker Compose before deployment.