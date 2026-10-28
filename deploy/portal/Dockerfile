# Public gateway in front of LangBot and SqlBot.
#
# Build on a networked machine, then ship the image together with the LangBot
# and SqlBot images for air-gapped hosts:
#
#   docker build -t langbot-portal-gateway:<tag> deploy/portal
FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf

RUN nginx -t
