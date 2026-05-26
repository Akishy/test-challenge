x-openresty-env: &openresty-env
  NGINX_TOTAL: "$nginx_total"
  FORWARD_PROBABILITY: "$forward_probability"
  APP_UPSTREAM: "app:8000"

x-openresty-common: &openresty-common
  image: openresty/openresty:alpine
  volumes:
    - ./nginx/nginx.conf:/usr/local/openresty/nginx/conf/nginx.conf:ro
    - ./nginx/lua:/etc/nginx/lua:ro
  depends_on:
    - app
  networks:
    - xffnet

services:
  app:
    image: python:3.12-alpine
    working_dir: /app
    volumes:
      - ./app:/app:ro
    command: python app.py
    networks:
      - xffnet

  lb:
    image: haproxy:2.9-alpine
    ports:
      - "8080:80"
    volumes:
      - ./lb/haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro
    depends_on:
$lb_depends_on
    networks:
      - xffnet

$nginx_services

networks:
  xffnet:
    driver: bridge