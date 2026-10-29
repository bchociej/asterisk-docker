FROM alpine:3.24 AS build
ARG ASTERISK_VERSION=22.11.0
ARG ASTERISK_SHA256=3bd5ee040509a3d3cd9b1ba9520c18e6ec0a7e7981ca68c457dcd36ba3c54d94
RUN apk add --no-cache build-base pkgconf curl ca-certificates bzip2 patch \
    bsd-compat-headers linux-headers libedit-dev util-linux-dev jansson-dev \
    libxml2-dev sqlite-dev openssl-dev libsrtp-dev ncurses-dev
WORKDIR /build
COPY patches/*.patch /patches/
RUN curl -fsSL "https://downloads.asterisk.org/pub/telephony/asterisk/releases/asterisk-${ASTERISK_VERSION}.tar.gz" -o asterisk.tar.gz \
    && echo "${ASTERISK_SHA256}  asterisk.tar.gz" | sha256sum -c - \
    && tar -xzf asterisk.tar.gz --strip-components=1 \
    && for patchfile in /patches/*.patch; do patch -p1 < "$patchfile"; done \
    && ./configure --enable-permanent-dlopen --disable-xmldoc --with-pjproject-bundled --without-jansson-bundled --with-ssl --with-srtp \
    && make menuselect.makeopts \
    && menuselect/menuselect --disable BUILD_NATIVE \
       --disable-category MENUSELECT_APPS --disable-category MENUSELECT_BRIDGES \
       --disable-category MENUSELECT_CDR --disable-category MENUSELECT_CEL \
       --disable-category MENUSELECT_CHANNELS --disable-category MENUSELECT_CODECS \
       --disable-category MENUSELECT_FORMATS --disable-category MENUSELECT_FUNCS \
       --disable-category MENUSELECT_PBX --disable-category MENUSELECT_RES \
       --disable-category MENUSELECT_CORE_SOUNDS --disable-category MENUSELECT_EXTRA_SOUNDS \
       --disable-category MENUSELECT_MOH menuselect.makeopts
COPY config/modules.conf /tmp/modules.conf
RUN set -eu; for module in $(sed -n 's/^load = \(.*\)\.so$/\1/p' /tmp/modules.conf); do \
        menuselect/menuselect --enable "$module" menuselect.makeopts; \
    done \
    && make -j4 \
    && make DESTDIR=/install install \
    && for module in $(sed -n 's/^load = \(.*\)\.so$/\1/p' /tmp/modules.conf); do \
        test -f "/install/usr/lib/asterisk/modules/$module.so"; \
    done

FROM alpine:3.24
LABEL org.opencontainers.image.title="Private Asterisk PBX" \
      org.opencontainers.image.description="Asterisk 22 LTS on Alpine for private LAN and WireGuard calls" \
      org.opencontainers.image.version="22.11.0"
RUN apk add --no-cache libedit libuuid jansson libxml2 sqlite-libs libssl3 libcrypto3 libsrtp ncurses-libs libstdc++ \
    && addgroup -g 10001 asterisk \
    && adduser -D -H -u 10001 -G asterisk -h /var/lib/asterisk -s /sbin/nologin asterisk \
    && mkdir -p /etc/asterisk /run/asterisk /var/lib/asterisk /var/spool/asterisk /var/log/asterisk
COPY --from=build /install/usr/ /usr/
COPY --from=build /install/var/lib/asterisk/ /var/lib/asterisk/
COPY config/ /etc/asterisk/
COPY scripts/healthcheck.sh /usr/local/bin/healthcheck
RUN chown -R 10001:10001 /var/lib/asterisk /run/asterisk /var/spool/asterisk /var/log/asterisk \
    && asterisk -V
USER 10001:10001
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 CMD ["/usr/local/bin/healthcheck"]
ENTRYPOINT ["/usr/sbin/asterisk"]
CMD ["-f", "-n", "-C", "/etc/asterisk/asterisk.conf"]
