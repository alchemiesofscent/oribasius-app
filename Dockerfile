FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create the database directory
RUN mkdir -p /app/instance

# Initialize the database
RUN python -c "from app import app, db; app.app_context().push(); db.create_all()"

EXPOSE 5000

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"]
