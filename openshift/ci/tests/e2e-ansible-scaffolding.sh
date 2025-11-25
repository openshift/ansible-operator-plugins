#!/usr/bin/env bash

source hack/lib/common.sh

set -eux

eval IMAGE=$IMAGE_FORMAT
ROOTDIR="$(pwd)"
GOTMP="$(mktemp -d -p $GOPATH/src)"
trap_add 'rm -rf $GOTMP' EXIT

mkdir -p $ROOTDIR/bin
export PATH=$ROOTDIR/bin:$PATH

# Install kubectl client
if ! [ -x "$(command -v kubectl)" ]; then
    curl -Lo kubectl https://storage.googleapis.com/kubernetes-release/release/v1.21.2/bin/linux/amd64/kubectl && chmod +x kubectl && mv kubectl bin/
fi

# Install oc client
if ! [ -x "$(command -v oc)" ]; then
    OPENSHIFT_CLIENT_VERSION="4.16.0"
    curl -Lo oc.tar.gz https://mirror.openshift.com/pub/openshift-v4/clients/ocp/${OPENSHIFT_CLIENT_VERSION}/openshift-client-linux-${OPENSHIFT_CLIENT_VERSION}.tar.gz
    tar xvzOf oc.tar.gz oc > oc && chmod +x oc && mv oc bin/ && rm oc.tar.gz
fi

# Printout where we're at and what we're using
oc version
echo $ROOTDIR

# install operator-sdk
# make install

# Test the operator
test_operator() {
    echo "Entered test_operator"

    # wait for operator pod to run
    if ! timeout 1m kubectl rollout status deployment/memcached-molecule-operator-controller-manager -n memcached-molecule-operator-system;
    then
        echo FAIL: operator failed to run
        kubectl describe pods
        kubectl logs deployment/memcached-molecule-operator-controller-manager -c manager
        exit 1
    fi


    # verify that metrics service was created
    if ! timeout 60s bash -c -- "until kubectl get service/memcached-molecule-operator-controller-manager-metrics-service > /dev/null 2>&1; do sleep 1; done";
    then
        echo "Failed to get metrics service"
        kubectl describe pods
        kubectl logs deployment/memcached-molecule-operator-controller-manager -c manager
        exit 1
    fi

    # create the service-account-token for the default service account
    cat <<EOF | kubectl apply -n memcached-molecule-operator-system -f -
apiVersion: v1
kind: Secret
type: kubernetes.io/service-account-token
metadata:
  name: service-account-secret
  annotations:
    kubernetes.io/service-account.name: "default"
EOF

    # get the serviceaccount token to access the metrics
    token=$(kubectl get secret service-account-secret -o jsonpath={.data.token} | base64 -d)


    # verify that the metrics endpoint exists
    if ! timeout 1m bash -c -- "until kubectl run --attach --rm --restart=Never test-metrics --image=registry.access.redhat.com/ubi8/ubi-minimal:latest -n memcached-molecule-operator-system --overrides='{\"spec\":{\"securityContext\":{\"runAsNonRoot\": true, \"capabilities\": {\"drop\": [\"ALL\"]}, \"allowPrivelegeEscalation\": false, \"seccompProfile\": {\"type\": \"RuntimeDefault\"}}}}' -- curl -sfkH \"Authorization: Bearer ${token}\" https://memcached-molecule-operator-controller-manager-metrics-service:8443/metrics; do sleep 1; done";
    then
        echo "Failed to verify that metrics endpoint exists"
        kubectl describe pods
        kubectl logs deployment/memcached-molecule-operator-controller-manager -c manager
        exit 1
    fi

    # create CR; this will trigger the reconcile and deploy memcached operand
    kubectl apply -f config/samples/cache_v1alpha1_memcached.yaml

    # wait until the deployment shows up
    if ! timeout 600s bash -c -- 'until kubectl get deployment memcached-sample-memcached; do sleep 1; done';
    then
        echo FAIL: operator failed to create memcached Deployment
        kubectl describe pods
        kubectl logs deployment/memcached-molecule-operator-controller-manager -c manager
        exit 1
    fi

    # wait until the deployment rollsout successfully
    if ! timeout 300s kubectl rollout status deployment/memcached-sample-memcached;
    then
        echo FAIL: memcached Deployment failed rollout
        kubectl describe pods
        kubectl logs deployment/memcached-molecule-operator-controller-manager -c manager
        kubectl logs deployment/memcached-sample-memcached
        exit 1
    fi

    # TODO: add finalizers back in
    # # make a configmap that the finalizer should remove
    # kubectl create configmap deleteme
    # trap_add 'kubectl delete --ignore-not-found configmap deleteme' EXIT

    # Delete the CR and wait for it to go away
    kubectl delete -f config/samples/cache_v1alpha1_memcached.yaml --wait=true

    # TODO: add finalizers back in
    # # if the finalizer did not delete the configmap...
    # if kubectl get configmap deleteme 2> /dev/null;
    # then
    #     echo FAIL: the finalizer did not delete the configmap
    #     kubectl describe pods
    #     kubectl logs deployment/memcached-molecule-operator-controller-manager -c manager
    #     exit 1
    # fi

    # The deployment should get garbage collected, so we expect to fail getting the deployment.
    if ! timeout 60s bash -c -- "while kubectl get deployment memcached-sample-memcached 2> /dev/null; do sleep 1; done";
    then
        echo FAIL: memcached Deployment did not get garbage collected
        kubectl describe pods
        kubectl logs deployment/memcached-molecule-operator-controller-manager -c manager
        exit 1
    fi

    # Ensure that no errors appear in the log
    if kubectl logs deployment/memcached-molecule-operator-controller-manager -c manager | grep -i error;
    then
        echo FAIL: the operator log includes errors
        kubectl describe pods
        kubectl logs deployment/memcached-molecule-operator-controller-manager -c manager
        exit 1
    fi
}

# use sample in testdata
pushd $ROOTDIR/testdata/memcached-molecule-operator
ls

# deploy operator
echo "running make deploy"
make deploy IMG=$IMAGE

# Hack: Add missing RBAC permission for operations related to `project.openshift.io`
# This is required for the Ansible Task: `create project if projects are available`
# TODO: Upstream PR to fix it: https://github.com/operator-framework/ansible-operator-plugins/pull/93
kubectl patch clusterrole memcached-molecule-operator-manager-role --type='json' -p='[
  {
    "op": "add",
    "path": "/rules/-",
    "value": {
      "apiGroups": ["project.openshift.io"],
      "resources": ["projectrequests", "projects"],
      "verbs": ["create", "delete", "get", "list", "patch", "update", "watch"]
    }
  }
]'

# Patch the deployment to increase memory limit to 1Gi to handle cluster-wide secret watching
echo "Patching deployment to increase memory limit to 1Gi"
kubectl patch deployment memcached-molecule-operator-controller-manager \
  -n memcached-molecule-operator-system \
  --type='json' \
  -p='[{"op": "replace", "path": "/spec/template/spec/containers/0/resources/limits/memory", "value": "1Gi"}]'

# create clusterrolebinding for metrics
kubectl create clusterrolebinding memcached-molecule-operator-metrics-reader-rolebinding --clusterrole=memcached-molecule-operator-metrics-reader --serviceaccount=memcached-molecule-operator-system:default

# switch to the "memcached-molecule-operator-system" namespace
oc project memcached-molecule-operator-system

# Test the operator
echo "running test_operator"
test_operator

# clean up the clusterrolebinding for metrics
kubectl delete clusterrolebinding memcached-molecule-operator-metrics-reader-rolebinding

# remove operator
echo "running make undeploy"
# Hack: Adding `--ignore-not-found` to avoid errors when some kustomized resources are deleted with namespace deletion
# TODO: Upstream PR to fix it: https://github.com/operator-framework/ansible-operator-plugins/pull/106
sed -i '/kubectl delete/ s/$/ --ignore-not-found/' Makefile
make undeploy

# the memcached-molecule-operator pods remain after the deployment is gone; wait until the pods are removed
echo "waiting for controller-manager pod to go away"
if ! timeout 60s bash -c -- "until kubectl get pods -l control-plane=controller-manager |& grep \"No resources found\"; do sleep 2; done";
then
    echo FAIL: memcached-molecule-operator Deployment did not get garbage collected
    kubectl describe pods
    kubectl logs deployment/memcached-molecule-operator-controller-manager -c manager
    exit 1
fi

popd
