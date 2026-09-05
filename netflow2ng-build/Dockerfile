# Builds netflow2ng from upstream source with one patch: formatter/mapping.yaml
# gains an `ipfix:` block (upstream PR #162, unmerged) so IPFIX flows carry
# byte/packet counters into ntopng instead of 0/0.
#
# Mirrors the upstream Dockerfile (https://github.com/synfinatic/netflow2ng),
# except the source is git-cloned here (self-contained build context) and the
# patched mapping.yaml from this directory is overlaid before compiling
# (the file is embedded into the binary at build time).
FROM golang:alpine AS builder

RUN apk update --no-cache && \
    apk add git build-base gcc pkgconfig zeromq-dev protoc && \
    apk add --repository=http://dl-cdn.alpinelinux.org/alpine/edge/testing protoc-gen-go

# Pin a ref for reproducibility; override with --build-arg NETFLOW2NG_REF=<sha/tag>
ARG NETFLOW2NG_REF=main
RUN git clone https://github.com/synfinatic/netflow2ng.git /build && \
    git -C /build checkout "${NETFLOW2NG_REF}"

# Overlay the IPFIX-patched mapping (embedded in the binary via go:embed)
COPY mapping.yaml /build/formatter/mapping.yaml

WORKDIR /build
RUN go mod download && \
    OUTPUT_NAME=dist/netflow2ng make

FROM alpine:latest

RUN apk update --no-cache && \
    apk add libzmq && \
    adduser -S -D -H -h / netflow
USER netflow
COPY --from=builder /build/dist/netflow2ng /

# ZMQ
EXPOSE 5556/tcp
# NetFlow v9/IPFIX
EXPOSE 2055/udp
# webserver
EXPOSE 8080/tcp
ENTRYPOINT ["/netflow2ng"]
