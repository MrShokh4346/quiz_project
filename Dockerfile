# Use official Python image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy bot code
COPY bot.py .
COPY telegram_quiz.json .

# Set environment variables (will override in Cloud Run)
ENV PORT=8080

# Command to run the bot
CMD ["python", "bot.py"]
