FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies for mysqlclient
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc \
        default-libmysqlclient-dev \
        pkg-config && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create dedicated non-root application user and group
RUN groupadd -r lendmate && \
    useradd -r -g lendmate -d /app -s /sbin/nologin lendmate

# Copy project files
COPY . .

# Collect static files during build
RUN DJANGO_SECRET_KEY=build-only-key DJANGO_DEBUG=true python manage.py collectstatic --noinput

# Set proper ownership and permissions for application and staticfiles
RUN chown -R lendmate:lendmate /app

# Switch to non-root user
USER lendmate

# Default port
EXPOSE 8000
