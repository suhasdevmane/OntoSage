FROM python:3.8-slim

# Install dependencies for the action server
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy the actions code
COPY . /app
COPY sensor_uuids.txt /app/sensor_uuids.txt
COPY sensor_list.txt /app/sensor_list.txt

# Set the working directory
WORKDIR /app

# Expose the action server port
EXPOSE 5055

# Command to run the action server (use rasa-sdk entrypoint, not rasa CLI)
CMD ["python", "-m", "rasa_sdk", "--actions", "actions"]