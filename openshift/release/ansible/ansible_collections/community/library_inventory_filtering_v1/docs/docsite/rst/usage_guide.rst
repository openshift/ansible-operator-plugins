..
  Copyright (c) Ansible Project
  GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
  SPDX-License-Identifier: GPL-3.0-or-later

.. _ansible_collections.community.library_inventory_filtering_v1.docsite.usage_guide:

Usage Guide
===========

The `community.library_inventory_filtering_v1 collection <https://galaxy.ansible.com/ui/repo/published/community/library_inventory_filtering_v1/>`_ enables other collections to add common filter functionality to inventory plugins.

.. contents::
   :local:
   :depth: 1


Requirements
------------

The ``stable-1`` branch of this collection, released as , works with all ansible-base and ansible-core versions, and with Ansible >= 2.9.10.

Adding filter functionality to an inventory plugin
--------------------------------------------------

The preferred way to use this collection is to use the ``inventory_filter`` docs fragment and the ``inventory_filter`` plugin utils.

To use the documentation fragment, add it to the ``extends_documentation_fragment`` list in ``DOCUMENTATION``:

.. code-block:: yaml

    extends_documentation_fragment:
      - community.library_inventory_filtering_v1.inventory_filter

For the filtering, you need to import two functions from the plugin util, ``parse_filters()`` and ``filter_host()``:

.. code-block:: python

    from ansible_collections.community.library_inventory_filtering_v1.plugins.plugin_utils.inventory_filter import (
        parse_filters,
        filter_host,
    )

You can use ``parse_filters()`` to parse the ``filters`` option's value (``self.get_option('filters')``), and ``filter_host()`` to determine whether to include a host:

.. code-block:: python

    class InventoryModule(BaseInventoryPlugin, ...):

        def parse(self, inventory, loader, path, cache=True):
            super(InventoryModule, self).parse(inventory, loader, path, cache)
            self._read_config_data(path)

            ...

            # Parse the filters option
            filters = parse_filters(self.get_option('filters'))

            ...

            for host in hosts:
                # Compile the host vars
                host_vars = ...

                # Now we can evaluate potential filter conditions
                # based on the host name and host vars:
                if not filter_host(self, host, host_vars, filters):
                    continue

                # Add the host with its vars
                self.inventory.add_host(name)
                for key, value in host_vars.items():
                    self.inventory.set_variable(name, key, value)

            ...
