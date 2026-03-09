module.exports = {
  apps: [{
    name: 'grant-viewer-api',
    script: 'backend/dist/index.js',
    cwd: '/home/clawd/Projects/grant-viewer-saas',
    env: {
      NODE_ENV: 'production',
      PORT: 3001,
      CORS_ORIGIN: '*',
    },
    instances: 1,
    autorestart: true,
    max_memory_restart: '256M',
  }],
};
