#!/bin/bash

# GitHub Actions経由でECR権限修正をデプロイするスクリプト
set -e

echo "🚀 Deploying ECR permission fixes via GitHub Actions..."
echo ""

# Git設定の確認
if ! git config --get user.name >/dev/null || ! git config --get user.email >/dev/null; then
    echo "⚠️ Git user configuration not found"
    echo "Please configure Git user:"
    echo "  git config --global user.name 'Your Name'"
    echo "  git config --global user.email 'your.email@example.com'"
    echo ""
fi

# 現在のブランチ確認
CURRENT_BRANCH=$(git branch --show-current)
echo "📍 Current branch: $CURRENT_BRANCH"

# 変更の確認
if ! git diff --quiet; then
    echo "📝 Uncommitted changes found:"
    git status --short
    echo ""
    
    echo "📋 Staging all changes..."
    git add .
    
    echo "💾 Committing changes..."
    git commit -m "fix: ECR authorization permissions for GitHub Actions

- Add ecr:GetAuthorizationToken permission for GitHub Actions role
- Enhance ECS operation permissions for deployment
- Add pass role permissions for ECS task execution
- Improve resource ARN specifications for better security

This fixes the ECR authentication error:
arn:aws:sts::*:assumed-role/whiskey-github-actions-role-dev/* is not authorized to perform: ecr:GetAuthorizationToken

Resolves GitHub Actions API deployment issues."
    
    echo "✅ Changes committed successfully"
else
    echo "ℹ️ No uncommitted changes found"
fi

# リモートの変更確認
echo "🔄 Checking for remote changes..."
git fetch origin

# プッシュの実行
if [[ "$CURRENT_BRANCH" == "main" ]]; then
    echo "🚀 Pushing to main branch (will trigger dev deployment)..."
    git push origin main
    
    echo ""
    echo "✅ Changes pushed to main branch!"
    echo ""
    echo "🔗 Monitor the deployment:"
    echo "   https://github.com/kter/whiskey/actions"
    echo ""
    echo "📊 Expected workflow:"
    echo "   1. Setup job - Get infrastructure outputs"
    echo "   2. Frontend deployment (parallel)"
    echo "   3. API deployment (parallel) - Should now succeed with ECR permissions"
    echo "   4. Notification"
    echo ""
    echo "⏱️ Deployment typically takes 5-10 minutes"
    
elif [[ "$CURRENT_BRANCH" == "production" ]]; then
    echo "🚀 Pushing to production branch (will trigger prod deployment)..."
    git push origin production
    
    echo ""
    echo "✅ Changes pushed to production branch!"
    echo "🔗 Monitor the deployment at: https://github.com/kter/whiskey/actions"
    
else
    echo "⚠️ Current branch is neither 'main' nor 'production'"
    echo "Available options:"
    echo "1. Push to current branch (no deployment):"
    echo "   git push origin $CURRENT_BRANCH"
    echo ""
    echo "2. Switch to main and push (dev deployment):"
    echo "   git checkout main && git merge $CURRENT_BRANCH && git push origin main"
    echo ""
    echo "3. Switch to production and push (prod deployment):"
    echo "   git checkout production && git merge $CURRENT_BRANCH && git push origin production"
    echo ""
    read -p "Enter choice (1/2/3) or press Enter to exit: " choice
    
    case $choice in
        1)
            git push origin "$CURRENT_BRANCH"
            echo "✅ Pushed to $CURRENT_BRANCH (no deployment triggered)"
            ;;
        2)
            git checkout main
            git merge "$CURRENT_BRANCH"
            git push origin main
            echo "✅ Deployed to dev environment via main branch"
            ;;
        3)
            git checkout production
            git merge "$CURRENT_BRANCH"
            git push origin production
            echo "✅ Deployed to prod environment via production branch"
            ;;
        *)
            echo "ℹ️ No action taken"
            exit 0
            ;;
    esac
fi

echo ""
echo "🎯 Next steps:"
echo "1. Monitor GitHub Actions workflow execution"
echo "2. Verify ECR authentication is working"
echo "3. Check API deployment success"
echo "4. Test API endpoints: https://api.dev.whiskeybar.site/health/" 