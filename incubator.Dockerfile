FROM python:3.8-slim
# 
WORKDIR /code
#
RUN apt update
#
RUN apt install -y htop
#
RUN apt install -y bmon
# 
COPY requirements.txt /code/
# 
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt
# 
