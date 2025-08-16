# pullin a python image
FROM python:3.12-slim 

# setting work dir to be app
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code to app directory
COPY . .

# Expose port
EXPOSE 8000

# Command to run the application
# Make FastAPI listen on port 80 (match ECS ALB port)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]