FROM registry.ci.openshift.org/ocp/builder:rhel-9-golang-1.22-openshift-4.17 AS builder

ENV GO111MODULE=on \
    GOFLAGS=-mod=vendor

COPY . /go/src/github.com/openshift/ansible-operator-plugins
RUN cd /go/src/github.com/openshift/ansible-operator-plugins \
 && make build

FROM registry.ci.openshift.org/ocp/4.17:base-rhel9

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
RUN yum clean all && rm -rf /var/cache/yum/* \
    && yum update -y \
    && yum install -y catatonit python3-cryptography python3-devel gcc python3-pip

# pip install will install a higher version of the requests module. However, pip fails
# to uninstall the existing request module as it is installed from rpm. Thus, removing
# the module before using pip install.
RUN yum remove -y python3-requests

# Add steps for cachito
ENV REMOTE_SOURCES=${REMOTE_SOURCES:-"./openshift/"}
ENV REMOTE_SOURCES_DIR=${REMOTE_SOURCES_DIR:-"/cachito"}
COPY ${REMOTE_SOURCES} ${REMOTE_SOURCES_DIR}
COPY openshift/install-ansible.sh .
RUN chmod +x /install-ansible.sh \
    && ./install-ansible.sh

# Remove packages which are only needed for cachito
RUN yum remove -y python3-devel gcc \
    && yum clean all \
    && rm -rf /var/cache/yum

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
