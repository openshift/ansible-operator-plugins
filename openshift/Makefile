# Get the directory where this Makefile is, so we can use it below for including
DIR := $(strip $(shell dirname $(realpath $(lastword $(MAKEFILE_LIST)))))

include $(addprefix $(DIR)/vendor/github.com/openshift/build-machinery-go/make/, \
    targets/openshift/deps.mk \
)

.PHONY: test-e2e-ansible
test-e2e-ansible:
	./openshift/ci/tests/e2e-ansible-scaffolding.sh

CONTAINER_ENGINE ?= docker
REQUIREMENTS_IMG ?= pip-requirements
COLLECTIONS_IMG ?= get-collections

.PHONY: build-requirements
build-requirements:
	$(CONTAINER_ENGINE) build -t $(REQUIREMENTS_IMG) -f openshift/Dockerfile.requirements .

# Use this target to generate the requirements.txt, requirements-build.txt and requirements-pre-build.txt
# files using the corresponding Pipfile and Pipfile.lock from the images/ansible-operator directory. The
# generated files will be used for building the image using cachito in the OSBS environment.
.PHONY: generate-requirements
generate-requirements: build-requirements
	$(CONTAINER_ENGINE) run --rm -it -v ./openshift:/tmp/requirements/:Z $(REQUIREMENTS_IMG)

.PHONY: check-requirements
check-requirements: generate-requirements
	git diff --exit-code # fast-fail if generate-requirements produced changes


.PHONY: build-collections
build-collections:
	$(CONTAINER_ENGINE) build -t $(COLLECTIONS_IMG) -f openshift/release/ansible/Dockerfile.collections .

.PHONY: update-collections
update-collections: build-collections
	rm -r ./openshift/release/ansible/ansible_collections
	$(CONTAINER_ENGINE) run -u $(shell id -u):$(shell id -g) --rm -it -v ./openshift/release/ansible:/tmp/ansible_collections/:Z $(COLLECTIONS_IMG)

.PHONY: check-collections
check-collections: update-collections
	git diff --exit-code # fast-fail if check-collections produced changes
