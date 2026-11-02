# The hosted manual: the released wheel, nothing from the checkout, so what
# runs there is what `pip install millwork` gives. The wheel comes from the
# GitHub release and sits next to this file when the image is built.
FROM python:3.12-slim

COPY millwork-*.whl /tmp/wheel/
RUN pip install --no-cache-dir /tmp/wheel/millwork-*.whl \
    && rm -r /tmp/wheel \
    && useradd --system --create-home --shell /usr/sbin/nologin millwork

USER millwork
ENV PYTHONUNBUFFERED=1
EXPOSE 8080

# Fly's proxy is in front: it ends TLS and forwards the visitor's address.
CMD ["millwork", "docs", "--host", "0.0.0.0", "--port", "8080", "--proxied"]
