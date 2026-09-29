FROM nginx:1.27-alpine
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY frontend/ /usr/share/nginx/html/
RUN rm -f /usr/share/nginx/html/Dockerfile /usr/share/nginx/html/nginx.conf
EXPOSE 80
