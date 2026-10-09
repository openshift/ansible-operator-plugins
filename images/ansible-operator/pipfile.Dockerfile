FROM registry.access.redhat.com/ubi9/ubi:9.4-1214.1726694543 AS basebuilder

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
RUN set -e && dnf clean all && rm -rf /var/cache/dnf/* \
  && dnf update -y \
  && dnf install -y gcc libffi-devel openssl-devel python3.12-devel \
  && pushd /usr/local/bin && ln -sf ../../bin/python3.12 python3 && popd \
  && python3 -m ensurepip --upgrade \
  && pip3 install --upgrade pip~=23.3.2 \
  && pip3 install pipenv==2023.11.15 \
  && pipenv lock \
  # NOTE: These ignored vulnerabilities are detected in transitive dependencies \
  # but the upgraded versions don't support the use case or are not yet available.\
  # 71064 (CVE-2024-35195), 90553: requests - upgraded version doesn't support the protocol we use.\
  # Ref: https://github.com/operator-framework/ansible-operator-plugins/pull/67#issuecomment-2189164688
  # SFTY-20260602-07854, SFTY-20260602-81653: jinja2 (3.1.6 is latest, no fix available) \
  # SFTY-20260721-32890 (CVE-2026-23490), SFTY-20260721-87910 (CVE-2026-30922): pyasn1 DoS (0.6.4 is latest, no fix available) \
  # 98479 (CVE-2026-45409): idna (3.20 is latest, no fix available)
  && pipenv check --ignore 71064 --ignore 90553 --ignore SFTY-20260602-07854 --ignore SFTY-20260602-81653 --ignore SFTY-20260721-32890 --ignore SFTY-20260721-87910 --ignore 98479 \
  && dnf remove -y gcc libffi-devel openssl-devel python3.12-devel \
  && dnf clean all \
  && rm -rf /var/cache/dnf

VOLUME /tmp/pip-airlock
ENTRYPOINT ["cp", "./Pipfile.lock", "/tmp/pip-airlock/"]
# to pull the generated lockfile, run this like 
# docker run --rm -it -v .:/tmp/pip-airlock:Z <image>
