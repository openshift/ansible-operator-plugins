# openshift-ansible-operator-plugins is built from the openshift/Dockerfile
FROM openshift-ansible-operator-plugins

COPY openshift/ci/testdata/ansible/memcached-operator/requirements.yml ${HOME}/requirements.yml
RUN ansible-galaxy collection install -r ${HOME}/requirements.yml \
 && chmod -R ug+rwx ${HOME}/.ansible

COPY openshift/ci/testdata/ansible/memcached-operator/watches.yaml ${HOME}/watches.yaml
COPY openshift/ci/testdata/ansible/memcached-operator/roles/ ${HOME}/roles/
COPY openshift/ci/testdata/ansible/memcached-operator/playbooks/ ${HOME}/playbooks/
