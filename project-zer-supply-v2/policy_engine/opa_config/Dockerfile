FROM openpolicyagent/opa:latest-static

COPY policies /policies

EXPOSE 8181

CMD ["run", "--server", "--addr", "0.0.0.0:8181", "--watch", "/policies"]
