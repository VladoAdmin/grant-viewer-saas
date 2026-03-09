module.exports = {
  apps: [
    {
      name: "grant-viewer-search-api",
      script: "python3",
      args: "-m scraper.search.api",
      cwd: "/home/clawd/Projects/grant-viewer-saas",
      interpreter: "none",
      autorestart: true,
      max_restarts: 10,
      restart_delay: 5000,
      env: {
        PYTHONUNBUFFERED: "1",
      },
    },
  ],
};
