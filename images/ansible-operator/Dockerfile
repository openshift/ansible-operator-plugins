# This Dockerfile defines the base image for the ansible-operator image.
# It is built with dependencies that take a while to download, thus speeding
# up ansible deploy jobs.

FROM registry.access.redhat.com/ubi8/ubi:8.9-1107 AS basebuilder

# Install Rust so that we can ensure backwards compatibility with installing/building the cryptography wheel across all platforms
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"
RUN rustc --version

# Copy python dependencies (including ansible) to be installed using Pipenv
COPY images/ansible-operator/Pipfile* ./
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
  && pipenv install --deploy \
  # NOTE: This ignored vulnerability (70612) was detected in jinja2, \
  # but the vulnerability is disputed and may never be fixed. See: \
  #  - https://github.com/advisories/GHSA-f6pv-j8mr-w6rr \
  #  - https://github.com/dbt-labs/dbt-core/issues/10250 \
  #  - https://data.safetycli.com/v/70612/97c/ \
  # 4.16 is Python 3.9. urllib3>=2.7 and ansible-core>=2.16 require Python>=3.10, \
  # so these Safety findings cannot be fixed on this stream (certifi-only bump). \
  # 90553 (CVE-2026-25645): requests - upgraded version doesn't support the protocol we use. \
  # 74261 / 73302 / SFTY-20260605-18433 (CVE-2026-11332): ansible-core 2.15.z is EOL. \
  # 96886 (CVE-2026-44431), SFTY-20260511-47957 (CVE-2026-44432), \
  # SFTY-20260930-39688 (CVE-2026-97687), SFTY-20260930-79283 (CVE-2026-97689), \
  # SFTY-20260930-11063 (CVE-2026-97688): urllib3 2.6.3 is the last 3.9-capable release. \
  && pipenv check --ignore 70612 --ignore 90553 --ignore 74261 --ignore 73302 \
       --ignore SFTY-20260605-18433 \
       --ignore 96886 --ignore SFTY-20260511-47957 \
       --ignore SFTY-20260930-39688 --ignore SFTY-20260930-79283 \
       --ignore SFTY-20260930-11063 \
  && yum remove -y gcc libffi-devel openssl-devel python39-devel \
  && yum clean all \
  && rm -rf /var/cache/yum

FROM registry.access.redhat.com/ubi8/ubi:8.9-1107 as base
ARG TARGETARCH

# Label this image with the repo and commit that built it, for freshmaking purposes.
ARG GIT_COMMIT=devel
LABEL git_commit=$GIT_COMMIT

RUN mkdir -p /etc/ansible \
  && echo "localhost ansible_connection=local" > /etc/ansible/hosts \
  && echo '[defaults]' > /etc/ansible/ansible.cfg \
  && echo 'roles_path = /opt/ansible/roles' >> /etc/ansible/ansible.cfg \
  && echo 'library = /usr/share/ansible/openshift' >> /etc/ansible/ansible.cfg

RUN set -e && yum clean all && rm -rf /var/cache/yum/* \
  && yum update -y \
  && yum install -y python39-pip python39-setuptools \
  && pip3 install --upgrade pip~=23.3.2 \
  && pip3 install pipenv==2023.11.15 \
  && yum clean all \
  && rm -rf /var/cache/yum

COPY --from=basebuilder /usr/local/lib64/python3.9/site-packages /usr/local/lib64/python3.9/site-packages
COPY --from=basebuilder /usr/local/lib/python3.9/site-packages /usr/local/lib/python3.9/site-packages
COPY --from=basebuilder /usr/local/bin /usr/local/bin

ENV TINI_VERSION=v0.19.0
RUN curl -L -o /tini https://github.com/krallin/tini/releases/download/${TINI_VERSION}/tini-${TARGETARCH} \
  && chmod +x /tini && /tini --version

# Final image.
FROM base

ENV HOME=/opt/ansible \
    USER_NAME=ansible \
    USER_UID=1001

# Ensure directory permissions are properly set
RUN echo "${USER_NAME}:x:${USER_UID}:0:${USER_NAME} user:${HOME}:/sbin/nologin" >> /etc/passwd \
  && mkdir -p ${HOME}/.ansible/tmp \
  && chown -R ${USER_UID}:0 ${HOME} \
  && chmod -R ug+rwx ${HOME}

WORKDIR ${HOME}
USER ${USER_UID}

COPY ansible-operator /usr/local/bin/ansible-operator

ENTRYPOINT ["/tini", "--", "/usr/local/bin/ansible-operator", "run", "--watches-file=./watches.yaml"]
