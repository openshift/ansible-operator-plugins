# Copyright (c), Felix Fontein <felix@fontein.de>, 2023
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type


import pytest

from ansible.errors import AnsibleError, AnsibleParserError
from ansible.template import Templar

from mock import MagicMock
from ansible_collections.community.internal_test_tools.tests.unit.mock.loader import DictDataLoader

from .....plugins.plugin_utils.inventory_filter import parse_filters, filter_host


@pytest.fixture(scope='module')
def inventory():
    r = MagicMock()
    r.templar = Templar(loader=DictDataLoader({}))
    return r


@pytest.mark.parametrize('input', [
    None,
    [],
    [{'include': 'foo'}],
    [{'include': True}],
    [{'exclude': 'foo'}],
    [{'exclude': False}],
])
def test_parse_success(input):
    result = parse_filters(input)
    print(result)
    assert result == (input or [])


@pytest.mark.parametrize('input, output', [
    (
        [23],
        ('filter[1] must be a dictionary', ),
    ),
    (
        [{}],
        ('filter[1] must have exactly one key-value pair', ),
    ),
    (
        [{'a': 'b', 'c': 'd'}],
        ('filter[1] must have exactly one key-value pair', ),
    ),
    (
        [{'foo': 'bar'}],
        ('filter[1] must have a "include" or "exclude" key, not "foo"', ),
    ),
    (
        [{'include': 23}],
        (
            "filter[1].include must be a string, not <class 'int'>",
            "filter[1].include must be a string, not <type 'int'>",
        ),
    ),
])
def test_parse_errors(input, output):
    with pytest.raises(AnsibleError) as exc:
        parse_filters(input)

    print(exc.value.args[0])
    assert exc.value.args[0] in output


@pytest.mark.parametrize('host, host_vars, filters, result', [
    (
        'example.com',
        {},
        [],
        True,
    ),
    (
        'example.com',
        {'foo': 'bar'},
        [{'include': 'inventory_hostname == "example.com"'}, {'exclude': 'true'}],
        True,
    ),
    (
        'example.com',
        {},
        [{'include': 'inventory_hostname == "foo.com"'}, {'exclude': 'false'}, {'exclude': True}],
        False,
    ),
])
def test_filter_success(inventory, host, host_vars, filters, result):
    assert filter_host(inventory, host, host_vars, filters) == result


@pytest.mark.parametrize('host, host_vars, filters, result', [
    (
        'example.com',
        {},
        [{'include': 'foobar'}],
        (
            "Could not evaluate filter condition 'foobar' for host example.com: 'foobar' is undefined",
            "Could not evaluate filter condition 'foobar' for host example.com: 'foobar' is undefined. 'foobar' is undefined",
        ),
    ),
])
def test_filter_errors(inventory, host, host_vars, filters, result):
    with pytest.raises(AnsibleParserError) as exc:
        filter_host(inventory, host, host_vars, filters)

    print(exc.value.args[0])
    assert exc.value.args[0] in result
