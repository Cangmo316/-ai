# 比邻AI 后端 · 容器镜像
#
# 为什么给学院服务器准备 Docker：
#   高校机房一般不允许随便 apt 装东西、也不希望你污染系统 Python。
#   容器化后对方只需要「装 docker → 起容器 → 给端口」，不需要懂 Python。
#   而且升级/回滚就是换镜像，不担心把机器搞坏。
#
#   python:3.12-slim 而不是 3.13：Ubuntu 24.04 / Debian 12 上 3.12 的轮子最全，
#   依赖全是纯 Python 包，3.12 与开发机的 3.13 行为一致（代码只用到 3.10+ 特性）。
FROM python:3.12-slim

# 时区：日志与 care/日期判断都依赖本地时间，容器默认 UTC 会让"今天几号"错一天
ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 只装运行期需要的最小依赖；curl 用于容器健康检查
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先拷 requirements 再拷代码：依赖没变时这层能命中缓存，重建只要几秒
COPY requirements.txt ./
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ \
      --trusted-host mirrors.aliyun.com -r requirements.txt

COPY . .

# 不以 root 跑：容器被突破时降权。数据目录要可写，所以先建好并改属主
RUN useradd --system --create-home --uid 10001 bilin \
 && mkdir -p /app/data /app/case_files /app/_voice_samples \
 && chown -R bilin:bilin /app/data /app/case_files /app/_voice_samples
USER bilin

EXPOSE 8000

# 健康检查用 /healthz（它在服务端是免鉴权的公开路径，见 app/auth.py PUBLIC_PATHS）
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

CMD ["python", "run.py"]
