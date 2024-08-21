# Get the directory where this Makefile is, so we can use it below for including
DIR := $(strip $(shell dirname $(realpath $(lastword $(MAKEFILE_LIST)))))

include $(addprefix $(DIR)/vendor/github.com/openshift/build-machinery-go/make/, \
    targets/openshift/deps.mk \
)

.PHONY: test-e2e-ansible
test-e2e-ansible:
	./openshift/ci/tests/e2e-ansible-scaffolding.sh
