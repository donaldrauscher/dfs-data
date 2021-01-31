FROM python:3.7-slim

ENV PYTHONUNBUFFERED True

ENV APP_HOME /app
WORKDIR $APP_HOME
COPY . ./

RUN pip install -r requirements.txt

RUN apt-get update -y \
  && apt-get install -y curl unzip wget \
  && GECKODRIVER_VERSION=`curl https://github.com/mozilla/geckodriver/releases/latest | grep -Po 'v[0-9]+.[0-9]+.[0-9]+'` \
  && wget https://github.com/mozilla/geckodriver/releases/download/$GECKODRIVER_VERSION/geckodriver-$GECKODRIVER_VERSION-linux64.tar.gz \
  && tar -zxf geckodriver-$GECKODRIVER_VERSION-linux64.tar.gz -C /usr/local/bin \
  && chmod +x /usr/local/bin/geckodriver \
  && apt-get install -y firefox-esr \
  && rm -rf /var/lib/apt/lists/*

CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 main:app