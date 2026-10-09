FROM python:3.11-slim-trixie

# Prevent python from writing pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies required for Playwright (if apt-get is needed)
RUN apt-get update && apt-get install -y \
    libicu76 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browser and its OS dependencies
RUN playwright install --with-deps chromium

# Copy the rest of the application
COPY . .

# Provision the pinned, checksum-verified native Office CLI for this build target.
# No host executable or upstream installer/MCP configuration is used.
RUN python scripts/install_officecli.py && OFFICECLI_SKIP_UPDATE=1 OFFICECLI_NO_AUTO_RESIDENT=1 vendor/officecli/officecli --version
RUN mkdir -p /opt/astakos-tools && cp vendor/officecli/officecli /opt/astakos-tools/officecli

# Expose port for the Setup Wizard / FastAPI
EXPOSE 8000

# Start Astakos using the bootstrap script
CMD ["python", "boot.py", "--server"]
