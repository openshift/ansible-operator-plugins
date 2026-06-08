FROM registry.redhat.io/ubi10/go-toolset:10.1 AS builder

USER root

ENV GO111MODULE=on \
    GOFLAGS=-mod=vendor

COPY . /go/src/github.com/openshift/ansible-operator-plugins
RUN cd /go/src/github.com/openshift/ansible-operator-plugins \
    && export SIMPLE_VERSION="$(make -pRrq --no-print-directory | grep '^IMAGE_VERSION' | awk -F'= ' '{print $2}')-ocp" \
    && export GIT_VERSION="$(make -pRrq --no-print-directory | grep '^IMAGE_VERSION' | awk -F'= ' '{print $2}')-ocp" \
    && make -e build

FROM registry.redhat.io/ubi10/ubi:10.1

RUN mkdir -p /etc/ansible \
    && echo "localhost ansible_connection=local" > /etc/ansible/hosts \
    && echo '[defaults]' > /etc/ansible/ansible.cfg \
    && echo 'roles_path = /opt/ansible/roles' >> /etc/ansible/ansible.cfg \
    && echo 'library = /usr/share/ansible/openshift' >> /etc/ansible/ansible.cfg

ENV HOME=/opt/ansible \
    USER_NAME=ansible \
    USER_UID=1001

# cryptography packages cannot be installed in the OSBS environment using pip.
# Thus installing it via rpm.
RUN dnf clean all && rm -rf /var/cache/dnf/* \
    && dnf update -y \
    && dnf install -y catatonit python3.12-cryptography python3.12-devel gcc \
    && pushd /usr/local/bin && ln -sf ../../bin/python3.12 python3 && popd \
    && python3 -m ensurepip --upgrade \
    # python3-six conflicts with pip-installed packages on RHEl/CentOS 10; remove it if present
    && { rpm -q python3-six && dnf remove -y python3-six || true; }

# Add steps for cachito
ENV REMOTE_SOURCES=${REMOTE_SOURCES:-"./openshift/"}
ENV REMOTE_SOURCES_DIR=${REMOTE_SOURCES_DIR:-"/cachito"}
COPY ${REMOTE_SOURCES} ${REMOTE_SOURCES_DIR}
# Copy our local ansible-runner-http replacement module
COPY images/ansible-operator/ansible_runner_http /ansible_runner_http
COPY openshift/install-ansible.sh .
# ubi10/ubi:10.1 ships many Python packages as RPM-managed installs that have
# no pip RECORD file, causing pip to fail when requirements.txt pins different
# versions. Remove all potentially conflicting RPM Python packages upfront so
# pip can install the pinned versions cleanly. Uses || true per package so the
# step succeeds even if a package is not present in the base image.
RUN for pkg in \
        python3-urllib3 \
        python3-six \
        python3-requests \
        python3-idna \
        python3-certifi \
        python3-charset-normalizer \
        python3-chardet \
        python3-resolvelib \
        python3-pyyaml \
        python3-pyasn1 \
        python3-pyasn1-modules \
        python3-oauthlib \
        python3-markupsafe \
        python3-jinja2 \
        python3-packaging \
        python3-dateutil \
        python3-pexpect \
        python3-ptyprocess \
        python3-lockfile \
        python3-rsa \
        python3-websocket-client; do \
        rpm -e --nodeps "$pkg" 2>/dev/null || true; \
    done \
    && chmod +x /install-ansible.sh \
    && ./install-ansible.sh

# Remove packages which are only needed for cachito
RUN dnf remove -y gcc \
    && dnf clean all \
    && rm -rf /var/cache/dnf

COPY --from=builder /go/src/github.com/openshift/ansible-operator-plugins/ansible-operator /usr/local/bin/ansible-operator
COPY openshift/release/ansible/ansible_collections ${HOME}/.ansible/collections/ansible_collections

# Ensure directory permissions are properly set
RUN echo "${USER_NAME}:x:${USER_UID}:0:${USER_NAME} user:${HOME}:/sbin/nologin" >> /etc/passwd \
    && mkdir -p ${HOME}/.ansible/tmp \
    && chown -R ${USER_UID}:0 ${HOME} \
    && chmod -R ug+rwx ${HOME}

WORKDIR ${HOME}
USER ${USER_UID}
ENTRYPOINT ["/usr/libexec/catatonit/catatonit", "--", "/usr/local/bin/ansible-operator", "run", "--watches-file=./watches.yaml"]
