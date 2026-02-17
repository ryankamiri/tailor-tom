FROM python:3.10-slim

# Install LaTeX engines (xelatex, lualatex, pdflatex) and required packages
# Using texlive-full for maximum compatibility (~5GB)
# For smaller size, use: texlive-latex-base texlive-latex-extra texlive-fonts-recommended texlive-latex-recommended texlive-xetex (~500MB)
# Also install fontconfig and common fonts for XeTeX/fontspec support
RUN sed -i 's/main/main contrib non-free/g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's/deb \(.*\) main/deb \1 main contrib non-free/g' /etc/apt/sources.list && \
    apt-get update && apt-get install -y \
    texlive-full \
    fontconfig \
    fonts-dejavu \
    fonts-dejavu-core \
    fonts-dejavu-extra \
    fonts-liberation \
    fonts-liberation2 \
    fonts-noto \
    fonts-noto-core \
    fonts-noto-extra \
    && rm -rf /var/lib/apt/lists/*

# Copy Microsoft Core Fonts (pre-downloaded to avoid 15+ minute downloads during build)
# This layer will be cached unless fonts/ directory changes
COPY backend/fonts/ /usr/share/fonts/truetype/msttcorefonts/
RUN fc-cache -fv

WORKDIR /app

# Copy requirements and install Python dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY backend/ /app/

EXPOSE 8000

# Run migrations then API (start-api.sh); worker uses separate command
RUN chmod +x /app/scripts/start-api.sh
CMD ["/app/scripts/start-api.sh"]

