#!/bin/bash
# Deploy Grant Viewer SaaS to StormLevel hosting
# Usage: ./deploy.sh

set -e

SSH_HOST="shell.r5.websupport.sk"
SSH_PORT=25254
SSH_USER="uid1125075"
SSH_PASS="923005954b"
REMOTE_DIR="/data/c/4/c4830825-2b90-47cd-b33d-145e854f9393/stormlevel.com/web/grant-viewer-saas"
NPM_GLOBAL_BIN="/data/c/4/c4830825-2b90-47cd-b33d-145e854f9393/.npm-global/bin"

echo "=== Grant Viewer SaaS Deploy ==="

# 1. Build
echo "1. Building frontend..."
cd frontend && VITE_API_URL=/api npm run build && cd ..

echo "2. Building backend..."
cd backend && npx tsc && cd ..

# 3. Prepare deploy package
echo "3. Preparing deploy package..."
DEPLOY_DIR=$(mktemp -d)
mkdir -p "$DEPLOY_DIR"/{backend,frontend,scraper}

# Backend: compiled JS + node_modules essentials
cp -r backend/dist "$DEPLOY_DIR/backend/"
cp backend/package.json backend/package-lock.json "$DEPLOY_DIR/backend/"

# Frontend: built static files
cp -r frontend/dist "$DEPLOY_DIR/frontend/"

# Scraper: Python code
cp -r scraper "$DEPLOY_DIR/"

# Config
cp .env "$DEPLOY_DIR/"

# PM2 ecosystem
cat > "$DEPLOY_DIR/ecosystem.config.js" << 'PM2CFG'
module.exports = {
  apps: [{
    name: 'grant-viewer-api',
    script: 'backend/dist/index.js',
    cwd: __dirname,
    env: {
      NODE_ENV: 'production',
      PORT: 3001,
      CORS_ORIGIN: 'https://stormlevel.com',
    },
    instances: 1,
    autorestart: true,
    max_memory_restart: '256M',
  }],
};
PM2CFG

echo "4. Uploading to StormLevel..."
sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no -p "$SSH_PORT" "$SSH_USER@$SSH_HOST" "mkdir -p $REMOTE_DIR"
sshpass -p "$SSH_PASS" scp -o StrictHostKeyChecking=no -P "$SSH_PORT" -r "$DEPLOY_DIR/"* "$SSH_USER@$SSH_HOST:$REMOTE_DIR/"

echo "5. Installing dependencies on server..."
sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no -p "$SSH_PORT" "$SSH_USER@$SSH_HOST" "
  cd $REMOTE_DIR/backend && npm install --production 2>&1 | tail -3
"

echo "6. Starting/restarting PM2..."
sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no -p "$SSH_PORT" "$SSH_USER@$SSH_HOST" "
  export PATH=$NPM_GLOBAL_BIN:\$PATH
  cd $REMOTE_DIR
  pm2 stop grant-viewer-api 2>/dev/null || true
  pm2 start ecosystem.config.js
  pm2 save
  pm2 list
"

# Cleanup
rm -rf "$DEPLOY_DIR"

echo ""
echo "=== Deploy complete ==="
echo "API: http://stormlevel.com:3001"
echo "Frontend: http://stormlevel.com:3001"
