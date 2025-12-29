FROM python:3.10-slim

# Install pdflatex and required LaTeX packages
# Using texlive-full for maximum compatibility (~5GB)
# For smaller size, use: texlive-latex-base texlive-latex-extra texlive-fonts-recommended texlive-latex-recommended (~500MB)
RUN apt-get update && apt-get install -y \
    texlive-full \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install Python dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY backend/ /app/

EXPOSE 8000

# Run the FastAPI application
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]

