#!/usr/bin/env bash
set -euo pipefail

# Frontend should be built during deploy (nixpacks build phase)
if [ ! -d "frontend/dist" ]; then
  echo "ERROR: frontend/dist not found. Ensure build phase runs npm install && npm run build."
  exit 1
fi

# Start API (port 8000)
uvicorn server:app --host 0.0.0.0 --port 8000 &

# Start Streamlit (port 8501)
streamlit run app.py --server.address 0.0.0.0 --server.port 8501 &

# Generate nginx config with Railway PORT
PORT=${PORT:-8080}
cat >/tmp/nginx.conf <<EOF
worker_processes 1;
error_log /dev/stderr info;
pid /tmp/nginx.pid;
events { worker_connections 1024; }
http {
  include       mime.types;
  default_type  application/octet-stream;
  sendfile      on;
  keepalive_timeout  65;

  upstream api { server 127.0.0.1:8000; }
  upstream ui { server 127.0.0.1:8501; }

  server {
    listen 0.0.0.0:${PORT};

    location /api/ {
      proxy_pass http://api/;
      proxy_set_header Host \$host;
      proxy_set_header X-Real-IP \$remote_addr;
      proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    }

    location /webrtc/ {
      proxy_pass http://api/webrtc/;
      proxy_set_header Host \$host;
    }

    location / {
      proxy_pass http://ui/;
      proxy_set_header Host \$host;
      proxy_set_header X-Real-IP \$remote_addr;
      proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
      proxy_set_header X-Forwarded-Proto \$scheme;
    }
  }
}
EOF

# Start nginx reverse proxy
nginx -c /tmp/nginx.conf -g 'daemon off;'
