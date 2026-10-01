FROM python:3.12-slim-trixie

WORKDIR /app

# Install PyMySQL + cryptography (required for MySQL 8 caching_sha2_password auth).
# PyYAML reads the building's feeds.yaml so the publisher can tell which wide-table columns
# a LIVE feed owns and leave those alone (BUG-888). Without it the publisher still runs, and
# says on stderr that feed columns are unprotected -- it does not pretend they are.
RUN pip install --no-cache-dir pymysql cryptography pyyaml

# Copy publisher script and data files
COPY mysql_dummy_publisher.py .
# The shaped-signal generator. Missing this COPY means the image imports
# nothing and the container dies on startup -- source correct, deployed thing
# broken, which is the BUG-343 pattern.
COPY sensor_signal.py .
COPY sensor_uuids.json .
COPY ["postgresql columns.csv", "."]

# Non-root user
RUN useradd -m -u 1000 publisher && chown -R publisher:publisher /app
USER publisher

CMD ["python", "-u", "mysql_dummy_publisher.py"]
