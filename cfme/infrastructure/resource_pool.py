# -*- coding: utf-8 -*-
import attr
from navmazing import NavigateToAttribute

from widgetastic.widget import View, Text
from widgetastic_patternfly import BreadCrumb, Button, Dropdown

from cfme.base.ui import BaseLoggedInPage
from cfme.common import Taggable
from cfme.exceptions import ResourcePoolNotFound, ItemNotFound
from cfme.modeling.base import BaseCollection, BaseEntity
from cfme.utils.appliance.implementations.ui import navigator, CFMENavigateStep, navigate_to
from cfme.utils.pretty import Pretty
from cfme.utils.wait import wait_for
from widgetastic_manageiq import (
    Accordion, BaseEntitiesView, ItemsToolBarViewSelector, ManageIQTree, SummaryTable, Search)


class ResourcePoolToolbar(View):
    """The toolbar on the main page"""
    configuration = Dropdown('Configuration')
    policy = Dropdown('Policy')
    download = Dropdown('Download')

    view_selector = View.nested(ItemsToolBarViewSelector)


class ResourcePoolDetailsToolbar(View):
    """The toolbar on the details page"""
    configuration = Dropdown('Configuration')
    policy = Dropdown('Policy')
    download = Button(title='Download summary in PDF format')


class ResourcePoolDetailsAccordion(View):
    """The accordian on the details page"""
    @View.nested
    class properties(Accordion):  # noqa
        tree = ManageIQTree()

    @View.nested
    class relationships(Accordion):  # noqa
        tree = ManageIQTree()


class ResourcePoolDetailsEntities(View):
    """Entities on the details page"""
    breadcrumb = BreadCrumb()
    title = Text('//div[@id="main-content"]//h1')
    properties = SummaryTable(title='Properties')
    relationships = SummaryTable(title='Relationships')
    smart_management = SummaryTable(title='Smart Management')


class ResourcePoolView(BaseLoggedInPage):
    """Base view for header and nav checking, navigatable views should inherit this"""
    title = Text('//div[@id="main-content"]//h1')

    @property
    def in_resource_pool(self):
        nav_chain = ['Compute', 'Infrastructure', 'Resource Pools']
        return (
            self.logged_in_as_current_user and
            self.navigation.currently_selected == nav_chain
        )


class ResourcePoolAllView(ResourcePoolView):
    """The "all" view -- a list of app the resource pools"""
    @property
    def is_displayed(self):
        return (
            self.in_resource_pool and
            self.entities.title.text == 'Resource Pools')

    toolbar = View.nested(ResourcePoolToolbar)
    search = View.nested(Search)
    including_entities = View.include(BaseEntitiesView, use_parent=True)


class ResourcePoolDetailsView(ResourcePoolView):
    """The details page of a resource pool"""
    @property
    def is_displayed(self):
        """Is this page being displayed?"""
        expected_title = '{} (Summary)'.format(self.context['object'].name)
        return (
            self.in_resource_pool and
            self.entities.title.text == expected_title and
            self.entities.breadcrumb.active_location == expected_title)

    toolbar = View.nested(ResourcePoolDetailsToolbar)
    sidebar = View.nested(ResourcePoolDetailsAccordion)
    entities = View.nested(ResourcePoolDetailsEntities)


@attr.s
class ResourcePool(Pretty, BaseEntity, Taggable):
    """ Model of an infrastructure Resource pool in cfme

    Args:
        name: Name of the Resource pool.
        provider: Provider object.

    """
    pretty_attrs = ['name', 'provider_key']
    quad_name = 'resource_pool'
    name = attr.ib()
    provider = attr.ib()

    def _get_context(self):
        context = {'resource_pool': self}
        if self.provider:
            context['provider'] = self.provider
        return context

    def delete(self, cancel=False, wait=False):
        """Deletes a resource pool from CFME

        Args:
            cancel: Whether or not to cancel the deletion, defaults to True
            wait: Whether or not to wait for the delete, defaults to False
        """
        view = navigate_to(self, 'Details')
        if self.appliance.version < '5.9':
            item_name = 'Remove Resource Pool'
        else:
            item_name = 'Remove Resource Pool from Inventory'
        view.toolbar.configuration.item_select(item_name, handle_alert=not cancel)

        # cancel doesn't redirect, confirmation does
        view.flush_widget_cache()
        if cancel:
            view = self.create_view(ResourcePoolDetailsView)
        else:
            view = self.create_view(ResourcePoolAllView)
        wait_for(lambda: view.is_displayed, fail_condition=False, num_sec=10, delay=1)

        # flash message only displayed if it was deleted
        if not cancel:
            msg = 'The selected Resource Pools was deleted'
            view.flash.assert_success_message(msg)

        if wait:
            def refresh():
                if self.provider:
                    self.provider.refresh_provider_relationships()
                view.browser.refresh()
                view.flush_widget_cache()

            wait_for(lambda: not self.exists, fail_condition=False, fail_func=refresh, num_sec=500,
                     message='Wait for resource pool to be deleted')

    def wait_for_exists(self):
        """Wait for the resource pool to be created"""
        view = navigate_to(self.parent, 'All')

        def refresh():
            if self.provider:
                self.provider.refresh_provider_relationships()
            view.browser.refresh()
            view.flush_widget_cache()

        wait_for(lambda: self.exists, fail_condition=False, num_sec=1000, fail_func=refresh,
                 message='Wait resource pool to appear')

    def get_detail(self, *ident):
        """ Gets details from the details infoblock

        The function first ensures that we are on the detail page for the specific resource pool.

        Args:
            ident: An InfoBlock title, followed by the Key name, e.g. "Properties"
        Returns:
            returns: A string representing the contents of the InfoBlock's value.
        """
        view = navigate_to(self, 'Details')
        table = None
        if ident[0] == 'Properties':
            table = view.properties
        elif ident[0] == 'Relationships':
            table = view.relationships
        elif ident[0] == 'Smart Management':
            table = view.smart_management
        if table:
            return table.get_text_of(ident[1])
        return None

    @property
    def exists(self):
        view = navigate_to(self.parent, 'All')
        return self.name in view.entities.entity_names


@attr.s
class ResourcePoolCollection(BaseCollection):
    """Collection object for the :py:class:`cfme.infrastructure.resource_pool.ResourcePool`."""

    ENTITY = ResourcePool

    # TODO: delete() when needed


@navigator.register(ResourcePoolCollection, 'All')
class All(CFMENavigateStep):
    """A navigation step for the All page"""
    VIEW = ResourcePoolAllView
    prerequisite = NavigateToAttribute('appliance.server', 'LoggedIn')

    def step(self, *args, **kwargs):
        self.prerequisite_view.navigation.select('Compute', 'Infrastructure', 'Resource Pools')


@navigator.register(ResourcePool, 'Details')
class Details(CFMENavigateStep):
    """A navigation step for the Details page"""
    VIEW = ResourcePoolDetailsView
    prerequisite = NavigateToAttribute('parent', 'All')

    def step(self, *args, **kwargs):
        """Navigate to the item"""
        try:
            row = self.prerequisite_view.entities.get_entity(name=self.obj.name, surf_pages=True)
        except ItemNotFound:
            raise ResourcePoolNotFound('Resource pool {} not found'.format(self.obj.name))
        row.click()
