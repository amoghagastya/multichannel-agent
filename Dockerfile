FROM python:3.11-slim

WORKDIR /app

# System deps: node + nginx + build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates gnupg \
    nginx \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 18
RUN curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get update && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY frontend/package.json frontend/package-lock.json* ./frontend/
RUN cd frontend && npm install

COPY . .
RUN cd frontend && npm run build

ENV PORT=8080

CMD ["bash", "deploy/start.sh"]
