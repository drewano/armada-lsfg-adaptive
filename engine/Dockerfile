# Builds the lsfg-vk Vulkan layer for aarch64 (Armada OS handhelds).
# The resulting .so + layer-info.json land in /backend/out and are bundled
# into the plugin zip as bin/.
#
# Build:
#   docker build --platform linux/arm64 -t armada-lsfg-backend ./backend
#   docker run --rm -v "$(pwd)/backend/out:/backend/out" armada-lsfg-backend
#
# Engine source is selectable:
#   --build-arg LSFG_SOURCE=experimental  (adaptive engine, eugeniosegala fork)
#   --build-arg LSFG_SOURCE=zensenshi     (aarch64-proven v1 engine, no adaptive)

FROM --platform=linux/arm64 fedora:41

ARG LSFG_SOURCE=experimental
ARG LSFG_REF=276030d4925c40038a61ecd66bd49ce777faec8c
ARG LSFG_ZENSENSHI_REF=main
ARG EXPERIMENTAL_REPO=https://github.com/eugeniosegala/lsfg-vk-experimental
ARG ZENSENSHI_REPO=https://github.com/Zensenshi/lsfg-vk-odin2-armada

RUN dnf -y --setopt=install_weak_deps=False install \
        cmake gcc-c++ make tar gzip curl ca-certificates python3 \
        vulkan-headers vulkan-loader-devel libX11-devel \
    && dnf clean all

ENV LSFG_SOURCE=${LSFG_SOURCE} \
    LSFG_REF=${LSFG_REF} \
    LSFG_ZENSENSHI_REF=${LSFG_ZENSENSHI_REF} \
    EXPERIMENTAL_REPO=${EXPERIMENTAL_REPO} \
    ZENSENSHI_REPO=${ZENSENSHI_REPO}

WORKDIR /work
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
