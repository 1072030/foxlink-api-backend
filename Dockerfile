# https://github.com/tiangolo/uvicorn-gunicorn-fastapi-docker

FROM tiangolo/uvicorn-gunicorn-fastapi:python3.8-slim

# set environment variables
ENV PYTHONWRITEBYTECODE 1
ENV PYTHONBUFFERED 1

ENV DATABASE_HOST=tonyyaovm.koreacentral.cloudapp.azure.com
ENV DATABASE_PORT=5587
ENV DATABASE_USER=foxlink_admin
ENV DATABASE_PASSWORD=8kFDgvdVLsvG
ENV DATABASE_NAME=foxlink
ENV JWT_SECRET=secret

# set working directory
WORKDIR /app

# copy dependencies
COPY requirements.txt /app/

# install dependencies
RUN pip install -r requirements.txt

# copy project
COPY . /app/

# expose port
EXPOSE 80
