FROM python:3.12-slim

WORKDIR /verify
COPY verify.py .

ENV API_URL=http://api:8000 \
    WEB_URL=http://web

CMD ["python", "verify.py"]
