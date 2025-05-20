# Copyright (c), Felix Fontein <felix@fontein.de>, 2023
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import absolute_import, division, print_function


__metaclass__ = type


import sys

import pytest
from ansible.errors import AnsibleError, AnsibleParserError
from ansible.template import Templar
from ansible_collections.community.internal_test_tools.tests.unit.mock.loader import (
    DictDataLoader,
)
from ansible_collections.community.internal_test_tools.tests.unit.utils.trust import (
    make_trusted,
)

from .....plugins.plugin_utils.inventory_filter import filter_host, parse_filters


if sys.version_info >= (3, 6):
    import typing

    if typing.TYPE_CHECKING:
        from .....plugins.plugin_utils.inventory_filter import (  # pragma: no cover
            _ExcludeFilter,
            _IncludeFilter,
        )

try:
    from unittest.mock import MagicMock
except ImportError:
    from mock import MagicMock


@pytest.fixture(name="inventory", scope="module")
def fixture_inventory():  # (...) -> typing.Any
    r = MagicMock()
    r.templar = Templar(loader=DictDataLoader({}))
    return r


DATA_TEST_PARSE_SUCCESS = [
    (
        None,
        [],
    ),
    (
        [],
        [],
    ),
    (
        [{"include": "foo"}],
        [{"include": "foo"}],
    ),
    (
        [{"include": True}],
        [{"include": True}],
    ),
    (
        [{"exclude": "foo"}],
        [{"exclude": "foo"}],
    ),
    (
        [{"exclude": False}],
        [{"exclude": False}],
    ),
    (
        [{"include": None, "exclude": False}],
        [{"exclude": False}],
    ),
]  # type: list[tuple[None | list[dict[str, typing.Any]], list[_IncludeFilter | _ExcludeFilter]]]


@pytest.mark.parametrize("filters, output", DATA_TEST_PARSE_SUCCESS)
def test_parse_success(
    filters,  # type: None | list[dict[str, typing.Any]]
    output,  # type: list[_IncludeFilter | _ExcludeFilter]
):  # type: (...) -> None
    result = parse_filters(filters)
    print(result)
    assert result == output


DATA_TEST_PARSE_ERRORS = [
    (
        [23],
        ("filter[1] must be a dictionary",),
    ),
    (
        [{}],
        ("filter[1] must have exactly one key-value pair",),
    ),
    (
        [{"a": "b", "c": "d"}],
        ("filter[1] must have exactly one key-value pair",),
    ),
    (
        [{"include": True, "foo": None}],
        ("filter[1] must have exactly one key-value pair",),
    ),
    (
        [{"foo": "bar"}],
        ('filter[1] must have a "include" or "exclude" key, not "foo"',),
    ),
    (
        [{"include": 23}],
        (
            "filter[1].include must be a string, not <class 'int'>",
            "filter[1].include must be a string, not <type 'int'>",
        ),
    ),
]  # type: list[tuple[list[typing.Any], tuple[str, ...]]]


@pytest.mark.parametrize("filters, output", DATA_TEST_PARSE_ERRORS)
def test_parse_errors(
    filters,  # type: list[typing.Any]
    output,  # tuple[str, ...]
):  # type: (...) -> None
    with pytest.raises(AnsibleError) as exc:
        parse_filters(filters)

    print(exc.value.args[0])
    assert exc.value.args[0] in output


DATA_TEST_FILTER_SUCCESS = [
    (
        "example.com",
        {},
        [],
        True,
    ),
    (
        "example.com",
        {"foo": "bar"},
        [
            {"include": make_trusted('inventory_hostname == "example.com"')},
            {"exclude": make_trusted("true")},
        ],
        True,
    ),
    (
        "example.com",
        {},
        [
            {"include": make_trusted('inventory_hostname == "foo.com"')},
            {"exclude": make_trusted("false")},
            {"exclude": True},
        ],
        False,
    ),
]  # type: list[tuple[str, dict[str, typing.Any], list[_IncludeFilter | _ExcludeFilter], bool]]


@pytest.mark.parametrize("host, host_vars, filters, result", DATA_TEST_FILTER_SUCCESS)
def test_filter_success(
    inventory,
    host,  # type: str
    host_vars,  # type: dict[str, typing.Any]
    filters,  # type: list[_IncludeFilter | _ExcludeFilter]
    result,  # type: bool
):  # type: (...) -> None
    assert filter_host(inventory, host, host_vars, filters) == result


DATA_TEST_FILTER_ERRORS = [
    (
        "example.com",
        {},
        [{"include": make_trusted("foobar")}],
        (
            "Could not evaluate filter condition 'foobar' for host example.com: Error while evaluating conditional: 'foobar' is undefined",
            "Could not evaluate filter condition 'foobar' for host example.com: 'foobar' is undefined",
            "Could not evaluate filter condition 'foobar' for host example.com: 'foobar' is undefined. 'foobar' is undefined",
        ),
    ),
]  # type: list[tuple[str, dict[str, typing.Any], list[_IncludeFilter | _ExcludeFilter], tuple[str, ...]]]


@pytest.mark.parametrize("host, host_vars, filters, result", DATA_TEST_FILTER_ERRORS)
def test_filter_errors(
    inventory,
    host,  # type: str
    host_vars,  # type: dict[str, typing.Any]
    filters,  # type: list[_IncludeFilter | _ExcludeFilter]
    result,  # type: tuple[str, ...]
):  # type: (...) -> None
    with pytest.raises(AnsibleParserError) as exc:
        filter_host(inventory, host, host_vars, filters)

    print(exc.value.args[0])
    assert exc.value.args[0] in result
