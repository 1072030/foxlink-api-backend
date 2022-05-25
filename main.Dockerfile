FROM python:3.8-slim

# 
WORKDIR /code

# 
COPY requirements.txt /code/
COPY prestart.sh /code/

# install cv2 dependencies
RUN apt-get update && apt-get install ffmpeg libsm6 libxext6 -y

# 
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt
# 
COPY . /code/

EXPOSE 80
RUN /code/prestart.sh
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "80"]