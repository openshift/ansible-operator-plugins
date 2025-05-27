#!/bin/bash

ansible-galaxy --version
ansible-galaxy collection install --force -r $(dirname "${BASH_SOURCE}")/requirements.yml -p $(dirname "${BASH_SOURCE}")
