# Builds the lsfg-vk Vulkan layer for aarch64 (Armada OS handhelds).
# The resulting .so + layer-info.json (+ lsfg-vk-cli when available) land in
# /engine/out and are bundled into the plugin zip as bin/.
#
# Build:
#   docker build --platform linux/arm64 -t armada-lsfg-backend ./engine
#   docker run --rm -v "$(pwd)/engine/out:/engine/out" armada-lsfg-backend
#
# Engine source is selectable:
#   --build-arg LSFG_SOURCE=upstream      (DEFAULT: PancakeTAS v2.0.0-dev,
#                                          the revision validated on Armada OS
#                                          hardware; fixed multipliers)
#   --build-arg LSFG_SOURCE=experimental  (eugeniosegala fork: adaptive engine,
#                                          not yet validated on Adreno)
#   --build-arg LSFG_SOURCE=zensenshi     (Zensenshi's aarch64 package source)

FROM --platform=linux/arm64 fedora:41

ARG LSFG_SOURCE=upstream
ARG LSFG_UPSTREAM_REF=8b0da2661c6f3473a7fccc8ba643880050e71642
ARG LSFG_REF=276030d4925c40038a61ecd66bd49ce777faec8c
ARG LSFG_ZENSENSHI_REF=main
ARG UPSTREAM_REPO=https://github.com/PancakeTAS/lsfg-vk
ARG EXPERIMENTAL_REPO=https://github.com/eugeniosegala/lsfg-vk-experimental
ARG ZENSENSHI_REPO=https://github.com/Zensenshi/lsfg-vk-odin2-armada

RUN dnf -y --setopt=install_weak_deps=False install \
        cmake gcc-c++ make tar gzip curl ca-certificates python3 \
        vulkan-headers vulkan-loader-devel libX11-devel \
    && dnf clean all

ENV LSFG_SOURCE=${LSFG_SOURCE} \
    LSFG_UPSTREAM_REF=${LSFG_UPSTREAM_REF} \
    LSFG_REF=${LSFG_REF} \
    LSFG_ZENSENSHI_REF=${LSFG_ZENSENSHI_REF} \
    UPSTREAM_REPO=${UPSTREAM_REPO} \
    EXPERIMENTAL_REPO=${EXPERIMENTAL_REPO} \
    ZENSENSHI_REPO=${ZENSENSHI_REPO}

WORKDIR /work
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
