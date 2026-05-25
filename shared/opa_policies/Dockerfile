# OPA (Open Policy Agent) Server Dockerfile
# Loads Rego policies from shared/opa_policies/zeroque/

FROM openpolicyagent/opa:latest

# Create policy directory
WORKDIR /policies

# Copy all Rego policies
COPY zeroque/*.rego /policies/zeroque/

# Expose OPA server port
EXPOSE 8181

# Run OPA server with policies loaded
# --server: Run in server mode
# --addr: Listen on all interfaces
# --log-level: info logging
CMD ["run", "--server", "--addr", ":8181", "--log-level", "info", "/policies"]
