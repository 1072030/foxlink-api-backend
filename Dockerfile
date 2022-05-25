# https://github.com/tiangolo/uvicorn-gunicorn-fastapi-docker

FROM tiangolo/uvicorn-gunicorn-fastapi:python3.8-slim

# set environment variables
ENV PYTHONWRITEBYTECODE 1
ENV PYTHONBUFFERED 1
# ENV MAX_WORKERS=1

# set working directory
WORKDIR /app

# copy dependencies
COPY requirements.txt /app/
COPY prestart.sh /app/

# install cv2 dependencies
RUN apt-get update && apt-get install ffmpeg libsm6 libxext6  -y

# install dependencies
RUN pip install -r requirements.txt

# copy project
COPY . /app/

# expose port
EXPOSE 80
