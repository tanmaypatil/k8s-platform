# Build image: JDK 8 + Maven 3.9.
# Build from the images/ directory so the shared build script is in context:
#   docker build -t k8s-platform/java8-maven:dev -f images/java8-maven/Dockerfile images
FROM maven:3.9.9-eclipse-temurin-8

LABEL org.opencontainers.image.title="k8s-platform java8-maven" \
      k8s-platform/java-version="8"

COPY build-scripts/run-build.sh /usr/local/bin/run-build
RUN chmod +x /usr/local/bin/run-build

WORKDIR /workspace
ENTRYPOINT ["run-build"]
