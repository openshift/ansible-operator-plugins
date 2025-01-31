# openshift-ansible-operator-plugins is built from the openshift/Dockerfile
FROM openshift-ansible-operator-plugins

COPY testdata/memcached-molecule-operator/requirements.yml ${HOME}/requirements.yml
RUN ansible-galaxy collection install -r ${HOME}/requirements.yml \
 && chmod -R ug+rwx ${HOME}/.ansible

COPY testdata/memcached-molecule-operator/watches.yaml ${HOME}/watches.yaml
COPY testdata/memcached-molecule-operator/roles/ ${HOME}/roles/
COPY testdata/memcached-molecule-operator/playbooks/ ${HOME}/playbooks/
