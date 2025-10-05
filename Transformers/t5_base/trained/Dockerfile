# Use the official Python base image
FROM python:3.9-slim

# Set the working directory
WORKDIR /app

# Copy requirements file
COPY requirements.txt .

# Upgrade pip and install dependencies
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    apt-get update && \
    apt-get install -y libprotobuf-dev protobuf-compiler && \
    pip install sentencepiece && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copy application files
COPY app.py .
COPY ./checkpoint-3 /app/checkpoint-3

# Expose port
EXPOSE 6005

# Run the application
CMD ["python", "app.py"]