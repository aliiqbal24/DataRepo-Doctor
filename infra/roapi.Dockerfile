FROM python:3.12-slim
RUN pip install --no-cache-dir roapi==0.12.7
ENTRYPOINT ["roapi"]
