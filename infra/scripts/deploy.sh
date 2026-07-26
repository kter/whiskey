#!/usr/bin/env bash

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'
MIN_BOOTSTRAP_VERSION=6

show_usage() {
  echo "Usage: $0 <dev|prd> <target> [target ...] [options]"
  echo
  echo "Targets (at least one is required):"
  echo "  --dns --oidc --cert --base --notifications --observability"
  echo "  --frontend        Generate and deploy the frontend"
  echo
  echo "Options:"
  echo "  --diff --diff-only --no-confirm --destroy"
  echo "  -c KEY=VALUE, --context KEY=VALUE (repeatable; env cannot be overridden)"
  exit 1
}

if [[ $# -eq 0 ]]; then
  show_usage
fi

ENVIRONMENT=$1
shift
if [[ "$ENVIRONMENT" != "dev" && "$ENVIRONMENT" != "prd" ]]; then
  echo -e "${RED}Error: environment must be 'dev' or 'prd'.${NC}"
  show_usage
fi

SHOW_DIFF=false
DIFF_ONLY=false
NO_CONFIRM=false
DESTROY=false
SELECT_DNS=false
SELECT_OIDC=false
SELECT_CERT=false
SELECT_BASE=false
SELECT_NOTIFICATIONS=false
SELECT_OBSERVABILITY=false
SELECT_FRONTEND=false
TARGET_COUNT=0
CDK_CONTEXT=(-c "env=$ENVIRONMENT")

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dns) SELECT_DNS=true; TARGET_COUNT=$((TARGET_COUNT + 1)) ;;
    --oidc) SELECT_OIDC=true; TARGET_COUNT=$((TARGET_COUNT + 1)) ;;
    --cert) SELECT_CERT=true; TARGET_COUNT=$((TARGET_COUNT + 1)) ;;
    --base) SELECT_BASE=true; TARGET_COUNT=$((TARGET_COUNT + 1)) ;;
    --notifications) SELECT_NOTIFICATIONS=true; TARGET_COUNT=$((TARGET_COUNT + 1)) ;;
    --observability) SELECT_OBSERVABILITY=true; TARGET_COUNT=$((TARGET_COUNT + 1)) ;;
    --frontend) SELECT_FRONTEND=true; TARGET_COUNT=$((TARGET_COUNT + 1)) ;;
    --diff) SHOW_DIFF=true ;;
    --diff-only) SHOW_DIFF=true; DIFF_ONLY=true ;;
    --no-confirm) NO_CONFIRM=true ;;
    --destroy) DESTROY=true ;;
    -c|--context)
      if [[ $# -lt 2 ]]; then
        echo -e "${RED}Error: $1 requires KEY=VALUE.${NC}"
        exit 2
      fi
      if [[ "$2" != *=* ]]; then
        echo -e "${RED}Error: context must use KEY=VALUE: $2${NC}"
        exit 2
      fi
      if [[ "$2" == env=* ]]; then
        echo -e "${RED}Error: context 'env' cannot be overridden; use the first argument.${NC}"
        exit 2
      fi
      CDK_CONTEXT+=(-c "$2")
      shift
      ;;
    -h|--help) show_usage ;;
    *) echo -e "${RED}Unknown option: $1${NC}"; show_usage ;;
  esac
  shift
done

if [[ $TARGET_COUNT -eq 0 ]]; then
  echo -e "${RED}Error: select at least one deployment target.${NC}"
  show_usage
fi
if [[ "$DESTROY" == true && ("$SELECT_DNS" == true || "$SELECT_OIDC" == true) ]]; then
  echo -e "${RED}Error: WhiskeyDns and WhiskeyGithubOidc cannot be destroyed by this script.${NC}"
  exit 2
fi
if [[ "$DESTROY" == true && "$SELECT_FRONTEND" == true ]]; then
  echo -e "${RED}Error: --frontend cannot be combined with --destroy.${NC}"
  exit 2
fi
if [[ "$ENVIRONMENT" == "prd" && "$SELECT_OIDC" == true ]]; then
  echo -e "${RED}Error: GitHub OIDC is a dev-account singleton stack.${NC}"
  exit 2
fi

cd "$(dirname "$0")/.."
PROFILE=$ENVIRONMENT
CDK_CONTEXT+=(--profile "$PROFILE")

command -v aws >/dev/null || { echo -e "${RED}Error: AWS CLI is not installed.${NC}"; exit 1; }
command -v npm >/dev/null || { echo -e "${RED}Error: npm is not installed.${NC}"; exit 1; }

echo -e "${YELLOW}Installing locked dependencies and validating TypeScript...${NC}"
npm ci
npx tsc --noEmit

EXPECTED_ACCOUNT=$(node -r ts-node/register -e \
  "const { environments } = require('./config/environments'); process.stdout.write(environments[process.argv[1]].account);" \
  "$ENVIRONMENT")
if [[ -z "$EXPECTED_ACCOUNT" ]]; then
  echo -e "${RED}Error: account for $ENVIRONMENT is not configured in config/environments.ts.${NC}"
  exit 1
fi

CALLER_ACCOUNT=$(aws sts get-caller-identity \
  --profile "$PROFILE" \
  --query Account \
  --output text)
if [[ "$CALLER_ACCOUNT" != "$EXPECTED_ACCOUNT" ]]; then
  echo -e "${RED}Error: profile $PROFILE resolves to $CALLER_ACCOUNT, expected $EXPECTED_ACCOUNT.${NC}"
  exit 1
fi

bootstrap_region() {
  local region=$1
  local version
  version=$(aws ssm get-parameter \
    --name /cdk-bootstrap/hnb659fds/version \
    --region "$region" \
    --profile "$PROFILE" \
    --query Parameter.Value \
    --output text 2>/dev/null || true)
  if [[ ! "$version" =~ ^[0-9]+$ || "$version" -lt "$MIN_BOOTSTRAP_VERSION" ]]; then
    echo -e "${YELLOW}Bootstrapping $EXPECTED_ACCOUNT/$region...${NC}"
    npx cdk bootstrap "aws://$EXPECTED_ACCOUNT/$region" \
      --profile "$PROFILE" \
      -c "env=$ENVIRONMENT"
  fi
}

if [[ "$SELECT_DNS" == true || "$SELECT_OIDC" == true || "$SELECT_CERT" == true \
  || "$SELECT_BASE" == true || "$SELECT_NOTIFICATIONS" == true \
  || "$SELECT_OBSERVABILITY" == true ]]; then
  bootstrap_region ap-northeast-1
  bootstrap_region us-east-1
fi

if [[ "$SELECT_NOTIFICATIONS" == true ]]; then
  for region in ap-northeast-1 us-east-1; do
    if ! aws ssm get-parameter \
      --name /whiskey/notifications/email \
      --region "$region" \
      --profile "$PROFILE" >/dev/null 2>&1; then
      echo -e "${RED}Error: /whiskey/notifications/email is missing in $region.${NC}"
      exit 1
    fi
  done
fi

ENV_NAME="${ENVIRONMENT^}"
STACKS=()
[[ "$SELECT_DNS" == true ]] && STACKS+=(WhiskeyDns)
[[ "$SELECT_OIDC" == true ]] && STACKS+=(WhiskeyGithubOidc)
[[ "$SELECT_CERT" == true ]] && STACKS+=("WhiskeyCertificate-$ENV_NAME")
if [[ "$SELECT_NOTIFICATIONS" == true ]]; then
  STACKS+=(WhiskeyNotifications WhiskeyNotifications-Tokyo)
fi
[[ "$SELECT_BASE" == true ]] && STACKS+=("WhiskeyApp-$ENV_NAME")
[[ "$SELECT_OBSERVABILITY" == true ]] && STACKS+=("WhiskeyObservability-$ENV_NAME")

if [[ "$SHOW_DIFF" == true ]]; then
  if [[ ${#STACKS[@]} -gt 0 ]]; then
    npx cdk diff "${STACKS[@]}" --exclusively "${CDK_CONTEXT[@]}"
  else
    echo -e "${YELLOW}No CDK stacks selected; there is no infrastructure diff for --frontend.${NC}"
  fi
  if [[ "$DIFF_ONLY" == true ]]; then
    exit 0
  fi
  if [[ "$NO_CONFIRM" != true ]]; then
    read -r -p "Continue? (yes/no): " REPLY
    [[ "$REPLY" =~ ^[Yy][Ee][Ss]$ ]] || exit 0
  fi
fi

if [[ "$ENVIRONMENT" == "prd" && "$NO_CONFIRM" != true && "$DESTROY" != true ]]; then
  read -r -p "Deploy production stacks? (yes/no): " REPLY
  [[ "$REPLY" =~ ^[Yy][Ee][Ss]$ ]] || exit 0
fi

if [[ ${#STACKS[@]} -gt 0 ]]; then
  if [[ "$DESTROY" == true ]]; then
    npx cdk destroy "${STACKS[@]}" --exclusively --force "${CDK_CONTEXT[@]}"
  else
    npx cdk deploy "${STACKS[@]}" --exclusively --require-approval never "${CDK_CONTEXT[@]}"
  fi
fi

if [[ "$SELECT_FRONTEND" == true ]]; then
  APP_STACK="WhiskeyApp-$ENV_NAME"
  FRONTEND_DIR="$(pwd)/../frontend"

  echo -e "${YELLOW}Reading frontend configuration from $APP_STACK...${NC}"
  STACK_OUTPUTS=$(aws cloudformation describe-stacks \
    --stack-name "$APP_STACK" \
    --region ap-northeast-1 \
    --profile "$PROFILE" \
    --query 'Stacks[0].Outputs' \
    --output json)

  get_stack_output() {
    local output_key=$1
    local output_value
    if ! output_value=$(node -e '
      const fs = require("fs");
      const outputs = JSON.parse(fs.readFileSync(0, "utf8"));
      const key = process.argv[1];
      const match = outputs.find((output) => output.OutputKey === key);
      if (!match || !match.OutputValue) process.exit(1);
      process.stdout.write(match.OutputValue);
    ' "$output_key" <<< "$STACK_OUTPUTS"); then
      echo -e "${RED}Error: stack output $output_key is missing from $APP_STACK.${NC}" >&2
      return 1
    fi
    printf '%s' "$output_value"
  }

  API_GATEWAY_URL=$(get_stack_output ApiGatewayUrl)
  CLOUDFRONT_DOMAIN=$(get_stack_output CloudFrontDomainName)
  DISTRIBUTION_ID=$(get_stack_output CloudFrontDistributionId)
  USER_POOL_ID=$(get_stack_output UserPoolId)
  USER_POOL_CLIENT_ID=$(get_stack_output UserPoolClientId)
  COGNITO_DOMAIN=$(get_stack_output CognitoHostedUiHostname)
  WEB_APP_BUCKET=$(get_stack_output WebAppBucketName)

  ENABLE_CUSTOM_DOMAIN=$(node -r ts-node/register -e \
    "const { environments } = require('./config/environments'); process.stdout.write(environments[process.argv[1]]?.enableCustomDomain === true ? 'true' : 'false');" \
    "$ENVIRONMENT")
  GOOGLE_AUTH_ENABLED=$(node -r ts-node/register -e \
    "const { environments } = require('./config/environments'); process.stdout.write(environments[process.argv[1]]?.enableGoogleAuth === true ? '1' : '0');" \
    "$ENVIRONMENT")

  if [[ "$ENABLE_CUSTOM_DOMAIN" == true ]]; then
    DOMAIN=$(node -r ts-node/register -e \
      "const { environments } = require('./config/environments'); process.stdout.write(environments[process.argv[1]]?.domain || '');" \
      "$ENVIRONMENT")
    if [[ -z "$DOMAIN" ]]; then
      echo -e "${RED}Error: enableCustomDomain is true but domain is not configured for $ENVIRONMENT.${NC}"
      exit 1
    fi
    API_BASE_URL="https://api.$DOMAIN"
  else
    API_BASE_URL=$API_GATEWAY_URL
  fi

  COGNITO_DOMAIN=${COGNITO_DOMAIN#https://}
  COGNITO_DOMAIN=${COGNITO_DOMAIN#http://}
  COGNITO_DOMAIN=${COGNITO_DOMAIN%%/*}
  if [[ -z "$COGNITO_DOMAIN" ]]; then
    echo -e "${RED}Error: CognitoHostedUiHostname did not contain a hostname.${NC}"
    exit 1
  fi

  echo "Frontend deployment configuration:"
  echo "  Stack: $APP_STACK"
  echo "  API base URL: $API_BASE_URL"
  echo "  CloudFront URL: https://$CLOUDFRONT_DOMAIN"
  echo "  CloudFront distribution: $DISTRIBUTION_ID"
  echo "  Web app bucket: $WEB_APP_BUCKET"
  echo "  User pool: $USER_POOL_ID"
  echo "  User pool client: $USER_POOL_CLIENT_ID"
  echo "  Cognito domain: $COGNITO_DOMAIN"
  echo "  Google auth enabled: $GOOGLE_AUTH_ENABLED"
  echo "  Environment: $ENVIRONMENT"

  if [[ -f "$FRONTEND_DIR/.env" ]]; then
    cp "$FRONTEND_DIR/.env" "$FRONTEND_DIR/.env.backup"
    echo "Backed up frontend/.env to frontend/.env.backup."
  fi

  {
    printf 'NUXT_PUBLIC_API_BASE_URL=%s\n' "$API_BASE_URL"
    printf 'NUXT_PUBLIC_USER_POOL_ID=%s\n' "$USER_POOL_ID"
    printf 'NUXT_PUBLIC_USER_POOL_CLIENT_ID=%s\n' "$USER_POOL_CLIENT_ID"
    printf 'NUXT_PUBLIC_REGION=ap-northeast-1\n'
    printf 'NUXT_PUBLIC_COGNITO_DOMAIN=%s\n' "$COGNITO_DOMAIN"
    printf 'NUXT_PUBLIC_GOOGLE_AUTH_ENABLED=%s\n' "$GOOGLE_AUTH_ENABLED"
    printf 'NUXT_PUBLIC_ENVIRONMENT=%s\n' "$ENVIRONMENT"
  } > "$FRONTEND_DIR/.env"

  echo -e "${YELLOW}Installing frontend dependencies and generating production assets...${NC}"
  (
    cd "$FRONTEND_DIR"
    npm ci
    env -u NUXT_PUBLIC_MOCK_AUTH NODE_ENV=production npm run generate

    echo -e "${YELLOW}Syncing generated assets to s3://$WEB_APP_BUCKET...${NC}"
    aws s3 sync .output/public "s3://$WEB_APP_BUCKET" --delete \
      --region ap-northeast-1 \
      --profile "$PROFILE"
  )

  echo -e "${YELLOW}Invalidating CloudFront distribution $DISTRIBUTION_ID...${NC}"
  aws cloudfront create-invalidation \
    --distribution-id "$DISTRIBUTION_ID" \
    --paths '/*' \
    --profile "$PROFILE"

  STACKS+=(frontend)
fi

echo -e "${GREEN}Operation completed for $ENVIRONMENT: ${STACKS[*]}${NC}"
