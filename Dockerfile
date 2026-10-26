# Deno is copied from the versioned official binary image, never curl | sh.
# Official image source: https://github.com/denoland/deno_docker
FROM denoland/deno:bin-2.9.8 AS deno

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=10000 \
    DOWNVIDEO_PUBLIC=1 \
    DOWNVIDEO_DATA_ROOT=/var/data \
    DOWNVIDEO_ACCESS_USER=owner \
    IMAGEIO_FFMPEG_EXE=/usr/bin/ffmpeg \
    DENO_DIR=/tmp/deno \
    DENO_NO_UPDATE_CHECK=1 \
    DENO_NO_PROMPT=1

RUN apt-get update \
    && apt-get install --no-install-recommends -y ca-certificates ffmpeg tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 downvideo \
    && useradd --uid 10001 --gid downvideo --create-home --shell /usr/sbin/nologin downvideo \
    && install -d -o downvideo -g downvideo /app /var/data /var/data/state /var/data/downloads

COPY --from=deno /deno /usr/local/bin/deno

WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir --target /app/.runtime/packages -r requirements.txt \
    && deno --version \
    && ffmpeg -version

# .dockerignore keeps local video files, Windows dependencies and secrets out.
COPY --chown=downvideo:downvideo . ./

USER 10001:10001
EXPOSE 10000

HEALTHCHECK --interval=30s --timeout=8s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '10000') + '/healthz', timeout=5).read()"

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "server.py"]

