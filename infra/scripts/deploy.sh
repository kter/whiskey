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
  echo "  --dns --oidc --cert --base --notifications"
  echo "  --observability   Reserved for a later task"
  echo "  --frontend        Reserved for a later task"
  echo
  echo "Options:"
  echo "  --diff --diff-only --no-confirm --destroy"
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
    -h|--help) show_usage ;;
    *) echo -e "${RED}Unknown option: $1${NC}"; show_usage ;;
  esac
  shift
done

if [[ $TARGET_COUNT -eq 0 ]]; then
  echo -e "${RED}Error: select at least one deployment target.${NC}"
  show_usage
fi
if [[ "$SELECT_FRONTEND" == true ]]; then
  echo -e "${RED}Error: --frontend is not implemented until Task 04.${NC}"
  exit 2
fi
if [[ "$SELECT_OBSERVABILITY" == true ]]; then
  echo -e "${YELLOW}Warning: --observability is planned for a later task; there is currently nothing to deploy.${NC}"
  if [[ $TARGET_COUNT -eq 1 ]]; then
    exit 0
  fi
fi
if [[ "$DESTROY" == true && ("$SELECT_DNS" == true || "$SELECT_OIDC" == true) ]]; then
  echo -e "${RED}Error: WhiskeyDns and WhiskeyGithubOidc cannot be destroyed by this script.${NC}"
  exit 2
fi
if [[ "$ENVIRONMENT" == "prd" && ("$SELECT_DNS" == true || "$SELECT_OIDC" == true) ]]; then
  echo -e "${RED}Error: DNS and GitHub OIDC are dev-account singleton stacks.${NC}"
  exit 2
fi

cd "$(dirname "$0")/.."
PROFILE=$ENVIRONMENT

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

bootstrap_region ap-northeast-1
bootstrap_region us-east-1

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
[[ "$SELECT_BASE" == true ]] && STACKS+=("WhiskeyApp-$ENV_NAME")
if [[ "$SELECT_NOTIFICATIONS" == true ]]; then
  STACKS+=(WhiskeyNotifications WhiskeyNotifications-Tokyo)
fi

CDK_CONTEXT=(-c "env=$ENVIRONMENT" --profile "$PROFILE")

if [[ "$SHOW_DIFF" == true ]]; then
  npx cdk diff "${STACKS[@]}" --exclusively "${CDK_CONTEXT[@]}"
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

if [[ "$DESTROY" == true ]]; then
  npx cdk destroy "${STACKS[@]}" --exclusively --force "${CDK_CONTEXT[@]}"
else
  npx cdk deploy "${STACKS[@]}" --exclusively --require-approval never "${CDK_CONTEXT[@]}"
fi

echo -e "${GREEN}Operation completed for $ENVIRONMENT: ${STACKS[*]}${NC}"
