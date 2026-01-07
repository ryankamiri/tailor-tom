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
    wget \
    cabextract \
    xfonts-utils \
    && echo "ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true" | debconf-set-selections \
    && apt-get install -y ttf-mscorefonts-installer \
    && rm -rf /var/lib/apt/lists/* \
    && fc-cache -fv

WORKDIR /app

# Copy requirements and install Python dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY backend/ /app/

EXPOSE 8000

# Run the FastAPI application
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]

