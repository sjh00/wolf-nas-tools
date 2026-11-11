# WolfNas 后端 Dockerfile
# 纯后端构建，前端由独立服务提供

FROM python:3.14-slim-trixie AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# 编译依赖
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    gcc libffi-dev libxml2-dev libxslt1-dev libssl-dev libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /wolfnas
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini run.py start-prod.sh start-dev.sh restart-server.sh stop-server.sh ./

ARG UV_INDEX_URL=https://pypi.org/simple
ENV UV_INDEX_URL=${UV_INDEX_URL}

# --no-install-package 的名字必须与 pyproject.toml 的 [project].name 一致，
# 否则 --frozen 会报 "Missing workspace member"。本项目 package = false
# （从源码运行），不为自身构建 wheel，因此排除掉项目自身即可。
RUN uv venv .venv \
    && uv sync --frozen --no-cache --no-install-package wolfnas

# ==================== 运行时 ====================
FROM python:3.14-slim-trixie

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ARG UV_INDEX_URL=https://pypi.org/simple
ENV UV_INDEX_URL=${UV_INDEX_URL}

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    nginx curl bash sudo tzdata wget xz-utils netcat-openbsd \
    libxml2 libxslt1.1 libffi8 libssl3 libpq5 ffmpeg unar \
    && rm -rf /var/lib/apt/lists/* /tmp/*

ARG S6_OVERLAY_VERSION=3.2.3.0
RUN set -eux; \
    S6_ARCH=$(case "$(uname -m)" in x86_64) echo "x86_64";; aarch64) echo "aarch64";; esac); \
    S6_BASE="https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}"; \
    for pkg in "s6-overlay-noarch.tar.xz" "s6-overlay-${S6_ARCH}.tar.xz" "s6-overlay-symlinks-noarch.tar.xz" "s6-overlay-symlinks-arch.tar.xz"; do \
        curl -fL --retry 6 --retry-all-errors --retry-delay 2 --connect-timeout 10 \
            "${S6_BASE}/${pkg}" -o "/tmp/${pkg}"; \
        tar -Jxpf "/tmp/${pkg}" -C /; \
        rm -f "/tmp/${pkg}"; \
    done

COPY --chmod=755 docker/rootfs /
RUN mkdir -p /var/log/nginx /var/run

ENV S6_SERVICES_GRACETIME=30000 \
    S6_KILL_GRACETIME=60000 \
    S6_CMD_WAIT_FOR_SERVICES_MAXTIME=0 \
    HOME="/wolfnas-home" \
    TERM="xterm" \
    LANG="C.UTF-8" \
    TZ="Asia/Shanghai" \
    WOLFNAS_CONFIG="/data/config.yaml" \
    WOLFNAS_DATA="/data" \
    PS1="\u@\h:\w \$ " \
    PUID=0 \
    PGID=0 \
    UMASK=000 \
    WOLFNAS_PORT=3000 \
    WORKDIR="/wolfnas"

# 运行期用户 wolfnas（UID/GID 911 与历史版本一致，升级后卷权限不受影响）
RUN groupadd -r -g 911 wolfnas \
    && useradd -r -g wolfnas -d ${HOME} -s /bin/bash -u 911 wolfnas \
    && mkdir -p ${WORKDIR} ${HOME} /data/logs \
    && echo "wolfnas ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers

WORKDIR ${WORKDIR}

COPY --chown=wolfnas:wolfnas . ${WORKDIR}/
COPY --from=builder --chown=wolfnas:wolfnas /wolfnas/.venv ${WORKDIR}/.venv

RUN chmod +x \
    ${WORKDIR}/start-prod.sh \
    ${WORKDIR}/start-dev.sh \
    ${WORKDIR}/restart-server.sh \
    ${WORKDIR}/stop-server.sh

HEALTHCHECK --interval=30s --timeout=30s --retries=3 \
    CMD wget -qO- http://localhost:8080/health || exit 1

# 两个端口务必区分，不能相同：
#   WOLFNAS_PORT      Python 应用内部端口（run.py 监听它，默认 3000）
#   8080              容器内 nginx 网关端口（固定，反代到 WOLFNAS_PORT）
# 容器对外只暴露 nginx 的 8080，所以 EXPOSE 写 8080；
# 把 WOLFNAS_PORT 也设成 8080 会让 Python 抢占 nginx 的端口，启动即报端口占用。
EXPOSE 8080
VOLUME ["/config"]
ENTRYPOINT ["/init"]
