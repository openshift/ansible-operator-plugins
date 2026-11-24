FROM registry.access.redhat.com/ubi8/ubi:8.9-1107 AS basebuilder

# Install Rust so that we can ensure backwards compatibility with installing/building the cryptography wheel across all platforms
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"
RUN rustc --version

# Copy python dependencies (including ansible) to be installed using Pipenv
COPY ./Pipfile ./
# Instruct pip(env) not to keep a cache of installed packages,
# to install into the global site-packages and
# to clear the pipenv cache as well
ENV PIP_NO_CACHE_DIR=1 \
    PIPENV_SYSTEM=1 \
    PIPENV_CLEAR=1
# Ensure fresh metadata rather than cached metadata, install system and pip python deps,
# and remove those not needed at runtime.
RUN set -e && yum clean all && rm -rf /var/cache/yum/* \
  && yum update -y \
  && yum install -y libffi-devel openssl-devel python39-devel gcc python39-pip python39-setuptools \
  && pip3 install --upgrade pip~=23.3.2 \
  && pip3 install pipenv==2023.11.15 \
  && pipenv lock \
  # 4.16 is Python 3.9. urllib3>=2.7 and ansible-core>=2.16 require Python>=3.10, \
  # so these Safety findings cannot be fixed on this stream (certifi-only bump). \
  # 90553 (CVE-2026-25645): requests - upgraded version doesn't support the protocol we use. \
  # 74261 / 73302 / SFTY-20260605-18433 (CVE-2026-11332): ansible-core 2.15.z is EOL. \
  # 96886 (CVE-2026-44431), SFTY-20260511-47957 (CVE-2026-44432), \
  # SFTY-20260930-39688 (CVE-2026-97687), SFTY-20260930-79283 (CVE-2026-97689), \
  # SFTY-20260930-11063 (CVE-2026-97688): urllib3 2.6.3 is the last 3.9-capable release. \
  && pipenv check --ignore 90553 --ignore 74261 --ignore 73302 \
       --ignore SFTY-20260605-18433 \
       --ignore 96886 --ignore SFTY-20260511-47957 \
       --ignore SFTY-20260930-39688 --ignore SFTY-20260930-79283 \
       --ignore SFTY-20260930-11063 \
  && yum remove -y gcc libffi-devel openssl-devel python39-devel \
  && yum clean all \
  && rm -rf /var/cache/yum

VOLUME /tmp/pip-airlock
ENTRYPOINT ["cp", "./Pipfile.lock", "/tmp/pip-airlock/"]
# to pull the generated lockfile, run this like 
# docker run --rm -it -v .:/tmp/pip-airlock:Z <image>
