FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN dir
RUN pip uninstall -y redis || true
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "run.py"]
