# Copyright (c) 2013 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.

"""
Management of the current context, e.g. the current shotgun entity/step/task.

"""

import os
import re
import pickle
import copy
import pprint

from tank_vendor import yaml
from . import authentication

from .util import login
from .util import shotgun_entity
from .util import shotgun
from . import constants
from .errors import TankError, TankContextDeserializationError
from .path_cache import PathCache
from .template import TemplatePath
from . import LogManager

log = LogManager.get_logger(__name__)


class Context(object):
    """
    A context instance is used to collect a set of key fields describing the
    current Context. We sometimes refer to the context as the current work area.
    Typically this would be the current shot or asset that someone is working on.

    The context captures the current point in both shotgun and the file system and context
    objects are launch a toolkit engine via the :meth:`sgtk.platform.start_engine`
    method. The context points the engine to a particular
    point in shotgun and on disk - it could be something as detailed as a task inside a Shot,
    and something as vague as an empty context.

    The context is split up into several levels of granularity, reflecting the
    fundamental hierarchy of Shotgun itself.

    - The project level defines which shotgun project the context reflects.
    - The entity level defines which entity the context reflects. For example,
      this may be a Shot or an Asset. Note that in the case of a Shot, the context
      does not contain any direct information of which sequence the shot is linked to,
      however the context can still resolve such relationships implicitly if needed -
      typically via the :meth:`Context.as_context_fields` method.
    - The step level defines the current pipeline step. This is often a reflection of a
      department or a general step in a workflow or pipeline (e.g. Modeling, Rigging).
    - The task level defines a current Shotgun task.
    - The user level defines the current user.

    The data forms a hierarchy, so implicitly, the task belongs to the entity which in turn
    belongs to the project. The exception to this is the user, which simply reflects the
    currently operating user.
    """

    def __init__(
        self, tk, project=None, entity=None, step=None, task=None, user=None,
        additional_entities=None, source_entity=None
    ):
        """
        Context objects are not constructed by hand but are fabricated by the
        methods :meth:`Sgtk.context_from_entity`, :meth:`Sgtk.context_from_entity_dictionary`
        and :meth:`Sgtk.context_from_path`.
        """
        self.__tk = tk
        self.__project = project
        self.__entity = entity
        self.__step = step
        self.__task = task
        self.__user = user
        self.__additional_entities = additional_entities or []
        self.__source_entity = source_entity
        self._entity_fields_cache = {}

    def __repr__(self):
        # multi line repr
        msg = []
        msg.append("  Project: %s" % str(self.__project))
        msg.append("  Entity: %s" % str(self.__entity))
        msg.append("  Step: %s" % str(self.__step))
        msg.append("  Task: %s" % str(self.__task))
        msg.append("  User: %s" % str(self.__user))
        msg.append("  Shotgun URL: %s" % self.shotgun_url)
        msg.append("  Additional Entities: %s" % str(self.__additional_entities))
        msg.append("  Source Entity: %s" % str(self.__source_entity))

        return "<Sgtk Context: %s>" % ("\n".join(msg))

    def __str__(self):
        """
        String representation for context
        """
        if self.project is None:
            # We're in a "site" context, so we'll give the site's url
            # minus the "https://" if that's attached.
            ctx_name = self.shotgun_url.split("//")[-1]

        elif self.entity is None:
            # project-only, e.g 'Project foobar'
            ctx_name = "Project %s" % self.project.get("name")

        elif self.step is None and self.task is None:
            # entity only
            # e.g. Shot ABC_123

            # resolve custom entities to their real display
            entity_display_name = shotgun.get_entity_type_display_name(
                self.__tk,
                self.entity.get("type")
            )

            ctx_name = "%s %s" % (
                entity_display_name,
                self.entity.get("name")
            )

        else:
            # we have either step or task
            task_step = None
            if self.step:
                task_step = self.step.get("name")
            if self.task:
                task_step = self.task.get("name")

            # e.g. Lighting, Shot ABC_123

            # resolve custom entities to their real display
            entity_display_name = shotgun.get_entity_type_display_name(
                self.__tk,
                self.entity.get("type")
            )

            ctx_name = "%s, %s %s" % (
                task_step,
                entity_display_name,
                self.entity.get("name")
            )

        return ctx_name

    def __eq__(self, other):
        """
        Test if this Context instance is equal to the other Context instance

        :param other:   The other Context instance to compare with
        :returns:       True if self represents the same context as other,
                        otherwise False
        """
        def _entity_dicts_eq(d1, d2):
            """
            Test to see if two entity dictionaries are equal.  They are considered
            equal if both are dictionaries containing 'type' and 'id' with the same
            values for both keys, For example:

            Comparing these two dictionaries would return True:
            - {"type":"Shot", "id":123, "foo":"foo"}
            - {"type":"Shot", "id":123, "foo":"bar", "bar":"foo"}

            But comparing these two dictionaries would return False:
            - {"type":"Shot", "id":123, "foo":"foo"}
            - {"type":"Shot", "id":567, "foo":"foo"}

            :param d1:  First entity dictionary
            :param d2:  Second entity dictionary
            :returns:   True if d1 and d2 are considered equal, otherwise False.
            """
            if d1 == d2 == None:
                return True
            if d1 == None or d2 == None:
                return False
            return d1["type"] == d2["type"] and d1["id"] == d2["id"]

        if not isinstance(other, Context):
            return NotImplemented

        if not _entity_dicts_eq(self.project, other.project):
            return False

        if not _entity_dicts_eq(self.entity, other.entity):
            return False

        if not _entity_dicts_eq(self.step, other.step):
            return False

        if not _entity_dicts_eq(self.task, other.task):
            return False
       
        # compare additional entities
        if self.additional_entities and other.additional_entities:
            # compare type, id tuples of all additional entities to ensure they are exactly the same.
            # this compare ignores duplicates in either list and just ensures that the intersection
            # of both lists contains all unique elements from both lists.
            types_and_ids = set([(e["type"], e["id"]) for e in self.additional_entities if e])
            other_types_and_ids = set([(e["type"], e["id"]) for e in other.additional_entities if e])
            if types_and_ids != other_types_and_ids:
                return False
        elif self.additional_entities or other.additional_entities:
            return False

        # finally compare the user - this may result in a Shotgun look-up
        # so do this last!
        if not _entity_dicts_eq(self.user, other.user):
            return False

        return True

    def __ne__(self, other):
        """
        Test if this Context instance is not equal to the other Context instance

        :param other:   The other Context instance to compare with
        :returns:       True if self != other, False otherwise
        """
        is_equal = self.__eq__(other)
        if is_equal is NotImplemented:
            return NotImplemented
        return not is_equal

    def __deepcopy__(self, memo):
        """
        Allow Context objects to be deepcopied - Note that the tk
        member is _never_ copied
        """
        # construct copy with current api instance:
        ctx_copy = Context(self.__tk)

        # deepcopy all other members:
        ctx_copy.__project = copy.deepcopy(self.__project, memo)
        ctx_copy.__entity = copy.deepcopy(self.__entity, memo)
        ctx_copy.__step = copy.deepcopy(self.__step, memo)
        ctx_copy.__task = copy.deepcopy(self.__task, memo)
        ctx_copy.__user = copy.deepcopy(self.__user, memo)
        ctx_copy.__additional_entities = copy.deepcopy(self.__additional_entities, memo)
        ctx_copy.__source_entity = copy.deepcopy(self.__source_entity, memo)

        # except:
        # ctx_copy._entity_fields_cache

        return ctx_copy

    ################################################################################################
    # properties

    @property
    def project(self):
        """
        The shotgun project associated with this context.

        If the context is incomplete, it is possible that the property is None. Example::

            >>> import sgtk
            >>> tk = sgtk.sgtk_from_path("/studio.08/demo_project")
            >>> ctx = tk.context_from_path("/studio.08/demo_project/sequences/AAA/ABC/Light/work")
            >>> ctx.project
            {'type': 'Project', 'id': 4, 'name': 'demo_project'}

        :returns: A std shotgun link dictionary with keys id, type and name, or None if not defined
        """
        return self.__project


    @property
    def entity(self):
        """
        The shotgun entity associated with this context.

        If the context is incomplete, it is possible that the property is None. Example::

            >>> import sgtk
            >>> tk = sgtk.sgtk_from_path("/studio.08/demo_project")
            >>> ctx = tk.context_from_path("/studio.08/demo_project/sequences/AAA/ABC/Light/work")
            >>> ctx.entity
            {'type': 'Shot', 'id': 412, 'name': 'ABC'}

        :returns: A std shotgun link dictionary with keys id, type and name, or None if not defined
        """
        return self.__entity

    @property
    def source_entity(self):
        """
        The Shotgun entity that was used to construct this Context.

        This is not necessarily the same as the context's "entity", as there
        are situations where a context is interpreted from an input entity,
        such as when a PublishedFile entity is used to determine a context. In
        that case, the original PublishedFile becomes the source_entity, and
        project, entity, task, and step are determined by what the
        PublishedFile entity is linked to. A specific example of where this is
        useful is in a pick_environment core hook. In that hook, an environment
        is determined based on a provided Context object. In the case where we want
        to provide a specific environment for a Context built from a PublishedFile
        entity, the context's source_entity can be used to know for certain that it
        was constructured from a PublishedFile.

        :returns: A Shotgun entity dictionary.
        :rtype: dict or None
        """
        return self.__source_entity

    @property
    def step(self):
        """
        The shotgun step associated with this context.

        If the context is incomplete, it is possible that the property is None. Example::

            >>> import sgtk
            >>> tk = sgtk.sgtk_from_path("/studio.08/demo_project")
            >>> ctx = tk.context_from_path("/studio.08/demo_project/sequences/AAA/ABC/Light/work")
            >>> ctx.step
            {'type': 'Step', 'id': 12, 'name': 'Light'}

        :returns: A std shotgun link dictionary with keys id, type and name, or None if not defined
        """
        return self.__step

    @property
    def task(self):
        """
        The shotgun task associated with this context.

        If the context is incomplete, it is possible that the property is None. Example::

            >>> import sgtk
            >>> tk = sgtk.sgtk_from_path("/studio.08/demo_project")
            >>> ctx = tk.context_from_path("/studio.08/demo_project/sequences/AAA/ABC/Lighting/first_pass_lgt/work")
            >>> ctx.task
            {'type': 'Task', 'id': 212, 'name': 'first_pass_lgt'}

        :returns: A std shotgun link dictionary with keys id, type and name, or None if not defined
        """
        return self.__task

    @property
    def user(self):
        """
        A property which holds the user associated with this context.
        If the context is incomplete, it is possible that the property is None.

        The user property is special - either it represents a user value that was baked
        into a template path upon folder creation, or it represents the current user::

            >>> import sgtk
            >>> tk = sgtk.sgtk_from_path("/studio.08/demo_project")
            >>> ctx = tk.context_from_path("/studio.08/demo_project/sequences/AAA/ABC/Lighting/dirk.gently/work")
            >>> ctx.user
            {'type': 'HumanUser', 'id': 23, 'name': 'Dirk Gently'}

        :returns: A std shotgun link dictionary with keys id, type and name, or None if not defined
        """
        # NOTE! get_shotgun_user returns more fields than just type, id and name
        # so make sure we get rid of those. We should make sure we return the data
        # in a consistent way, similar to all other entities. No more. No less.
        if self.__user is None:
            user = login.get_current_user(self.__tk)
            if user is not None:
                self.__user = {"type": user.get("type"),
                               "id": user.get("id"),
                               "name": user.get("name")}
        return self.__user

    @property
    def additional_entities(self):
        """
        List of entities that are required to provide a full context in non-standard configurations.
        The "context_additional_entities" core hook gives the context construction code hints about how
        this data should be populated.

        .. warning:: This is an old and advanced option and may be deprecated in the future. We strongly
                     recommend not using it.

        :returns: A list of std shotgun link dictionaries.
                  Will be an empty list in most cases.
        """
        return self.__additional_entities

    @property
    def entity_locations(self):
        """
        A list of paths on disk which correspond to the **entity** which this context represents.
        If no folders have been created for this context yet, the value of this property will be an empty list::


            >>> import sgtk
            >>> tk = sgtk.sgtk_from_path("/studio.08/demo_project")
            >>> ctx = tk.context_from_entity("Task", 8)
            >>> ctx.entity_locations
            ['/studio.08/demo_project/sequences/AAA/ABC']

        :returns: A list of paths
        """
        if self.entity is None:
            return []

        paths = self.__tk.paths_from_entity(self.entity["type"], self.entity["id"])

        return paths

    @property
    def shotgun_url(self):
        """
        Returns the shotgun detail page url that best represents this context. Depending on
        the context, this may be a task, a shot, an asset or a project. If the context is
        completely empty, the root url of the associated shotgun installation is returned.

            >>> import sgtk
            >>> tk = sgtk.sgtk_from_path("/studio.08/demo_project")
            >>> ctx = tk.context_from_entity("Task", 8)
            >>> ctx.shotgun_url
            'https://mystudio.shotgunstudio.com/detail/Task/8'
        """

        # walk up task -> entity -> project -> site

        if self.task is not None:
            return "%s/detail/%s/%d" % (self.__tk.shotgun_url, "Task", self.task["id"])

        if self.entity is not None:
            return "%s/detail/%s/%d" % (self.__tk.shotgun_url, self.entity["type"], self.entity["id"])

        if self.project is not None:
            return "%s/detail/%s/%d" % (self.__tk.shotgun_url, "Project", self.project["id"])

        # fall back on just the site main url
        return self.__tk.shotgun_url

    @property
    def filesystem_locations(self):
        """
        A property which holds a list of paths on disk which correspond to this context.
        If no folders have been created for this context yet, the value of this property will be an empty list::

            >>> import sgtk
            >>> tk = sgtk.sgtk_from_path("/studio.08/demo_project")
            >>> ctx = tk.context_from_entity("Task", 8)
            >>> ctx.filesystem_locations
            ['/studio.08/demo_project/sequences/AAA/ABC/light/initial_pass']

        :returns: A list of paths
        """

        # first handle special cases: empty context
        if self.project is None:
            return []

        # first handle special cases: project context
        if self.entity is None:
            return self.__tk.paths_from_entity("Project", self.project["id"])

        # at this stage we know that the context contains an entity
        # start off with all the paths matching this entity and then cull it down
        # based on constraints.
        entity_paths = self.__tk.paths_from_entity(self.entity["type"], self.entity["id"])

        # for each of these paths, get the context and compare it against our context
        # todo: optimize this!
        matching_paths = []
        for p in entity_paths:
            ctx = self.__tk.context_from_path(p)
            # the stuff we need to compare against are all the "child" levels
            # below entity: task and user
            matching = False
            if ctx.user is None and self.user is None:
                # no user data in either context
                matching = True
            elif ctx.user is not None and self.user is not None:
                # both contexts have user data - is it matching?
                if ctx.user["id"] == self.user["id"]:
                    matching = True

            if matching:
                # ok so user looks good, now check task.
                # it is possible that with a context that comes from shotgun
                # there is a task populated which is not being used in the file system
                # so when we compare tasks, only if there are differing task ids,
                # we should treat it as a mismatch.
                task_matching = True
                if ctx.task is not None and self.task is not None:
                    if ctx.task["id"] != self.task["id"]:
                        task_matching = False

                if task_matching:
                    # both user and task is matching
                    matching_paths.append(p)

        return matching_paths

    @property
    def sgtk(self):
        """
        The Toolkit API instance associated with this context

        :returns: :class:`Sgtk`
        """
        return self.__tk

    @property
    def tank(self):
        """
        Legacy equivalent of :meth:`sgtk`

        :returns: :class:`Sgtk`
        """
        return self.__tk

    ################################################################################################
    # public methods

    def as_template_fields(self, template=None, validate=False):
        """
        Returns the context object as a dictionary of template fields.

        This is useful if you want to use a Context object as part of a call to
        the Sgtk API. In order for the system to pass suitable values, you need to
        pass the template you intend to use the data with as a parameter to this method.
        The values are derived from existing paths on disk, or in the case of keys with
        shotgun_entity_type and shotgun_entity_field settings, direct queries to the Shotgun
        server. The validate parameter can be used to ensure that the method returns all
        context fields required by the template and if it can't then a :class:`TankError` will be raised.
        Example::

            >>> import sgtk
            >>> tk = sgtk.sgtk_from_path("/studio.08/demo_project")

            # Create a template based on a path on disk. Because this path has been
            # generated through Toolkit's folder processing and there are corresponding
            # FilesystemLocation entities stored in Shotgun, the context can resolve
            # the path into a set of Shotgun entities.
            #
            # Note how the context object, once resolved, does not contain
            # any information about the sequence associated with the Shot.
            >>> ctx = tk.context_from_path("/studio.08/demo_project/sequences/AAA/ABC/Lighting/work")
            >>> ctx.project
            {'type': 'Project', 'id': 4, 'name': 'demo_project'}
            >>> ctx.entity
            {'type': 'Shot', 'id': 2, 'name': 'ABC'}
            >>> ctx.step
            {'type': 'Step', 'id': 1, 'name': 'Light'}

            # now if we have a template object that we want to turn into a path,
            # we can request that the context object attempts to resolve as many
            # fields as it can. These fields can then be plugged into the template
            # object to generate a path on disk
            >>> templ = tk.templates["maya_shot_publish"]
            >>> templ
            <Sgtk TemplatePath maya_shot_publish: sequences/{Sequence}/{Shot}/{Step}/publish/{name}.v{version}.ma>

            >>> fields = ctx.as_template_fields(templ)
            >>> fields
            {'Step': 'Lighting', 'Shot': 'ABC', 'Sequence': 'AAA'}

            # the fields dictionary above contains all the 'high level' data that is necessary to realise
            # the template path. An app or integration can now go ahead and populate the fields specific
            # for the app's business logic - in this case name and version - and resolve the fields dictionary
            # data into a path.


        :param template:    :class:`Template` for which the fields will be used.
        :param validate:    If True then the fields found will be checked to ensure that all expected fields for
                            the context were found.  If a field is missing then a :class:`TankError` will be raised
        :returns:           A dictionary of template files representing the context. Handy to pass to for example
                            :meth:`Template.apply_fields`.
        :raises:            :class:`TankError` if the fields can't be resolved for some reason or if 'validate' is True
                            and any of the context fields for the template weren't found.
        """
        # Get all entities into a dictionary
        entities = {}

        if self.entity:
            entities[self.entity["type"]] = self.entity
        if self.step:
            entities["Step"] = self.step
        if self.task:
            entities["Task"] = self.task
        if self.user:
            entities["HumanUser"] = self.user
        if self.project:
            entities["Project"] = self.project

        # If there are any additional entities, use them as long as they don't
        # conflict with types we already have values for (Step, Task, Shot/Asset/etc)
        for add_entity in self.additional_entities:
            if add_entity["type"] not in entities:
                entities[add_entity["type"]] = add_entity

        fields = {}

        if template:
            keys = template.keys.values()
        else:
            keys = self.tk.template_keys.values()

        # First attempt to get fields from the entities stored in the context
        fields.update(self._fields_from_entities(keys, entities))
        keys = self._get_missing_keys(keys, fields, entities)
        if not keys:
            return fields

        # Try to populate fields using paths caches for entity
        if isinstance(template, TemplatePath):

            # first, sanity check that we actually have a path cache entry
            # this relates to ticket 22541 where it is possible to create
            # a context object purely from Shotgun without having it in the path cache
            # (using tk.context_from_entity(Task, 1234) for example)
            #
            # Such a context can result in erronous lookups in the later commands
            # since these make the assumption that the path cache contains the information
            # that is being saught after.
            #
            # therefore, if the context object contains an entity object and this entity is
            # not represented in the path cache, raise an exception.
#            if self.entity and len(self.entity_locations) == 0:
#                # context has an entity associated but no path cache entries
#                raise TankError("Cannot resolve template data for context '%s' - this context "
#                                "does not have any associated folders created on disk yet and "
#                                "therefore no template data can be extracted. Please run the folder "
#                                "creation for %s and try again!" % (self, self.shotgun_url))

            # first look at which ENTITY paths are associated with this context object
            # and use these to extract the right fields for this template
            tmp_fields = self._fields_from_entity_paths(template)

            # filter the list of fields to just those that don't have a 'None' value.
            # Note: A 'None' value for a field indicates an ambiguity and was set in the
            # _fields_from_entity_paths method (!)
            fields.update(dict([(key, value) for key, value in tmp_fields.iteritems() if value is not None]))
            keys = self._get_missing_keys(keys, fields, entities)
            if not keys:
                return fields

            # Determine additional field values by walking down the template tree
            fields.update(self._fields_from_template_tree(template, fields, entities))
            keys = self._get_missing_keys(keys, fields, entities)
            if not keys:
                return fields

        # get values for shotgun query keys in template
        fields.update(self._fields_from_shotgun(keys, entities))
        keys = self._get_missing_keys(keys, fields, entities)

        # If we still have keys, then we haven't fully solved
        if keys and validate:
                raise TankError("Cannot resolve template fields for context '%s' - the following "
                                "keys could not be resolved: '%s'.  Please run the folder creation "
                                "for '%s' and try again!"
                            % (self, ", ".join([x.name for x in keys]), self.shotgun_url))

        return fields


    def _get_missing_keys(self, keys, fields, entities, validate=False):
        """
        Returns a list of shotgun keys that don't have field values yet
        """
        missing_keys = []
        for key in keys:
            if key.shotgun_entity_type:
                if key.name not in fields:
                    # we have a template key that should have been found but wasn't!
                    missing_keys.append(key)

        return missing_keys


    def create_copy_for_user(self, user):
        """
        Provides the ability to create a copy of an existing Context for a specific user.

        This is useful if you need to determine a user specific version of a path, e.g.
        when copying files between different user sandboxes. Example::

            >>> import sgtk
            >>> tk = sgtk.sgtk_from_path("/studio.08/demo_project")
            >>> ctx = tk.context_from_path("/studio.08/demo_project/sequences/AAA/ABC/Lighting/dirk.gently/work")
            >>> ctx.user
            {'type': 'HumanUser', 'id': 23, 'name': 'Dirk Gently'}
            >>>
            >>> copied_ctx = tk.create_copy_for_user({'type': 'HumanUser', 'id': 7, 'name': 'John Snow'})
            >>> copied_ctx.user
            {'type': 'HumanUser', 'id': 23, 'name': 'John Snow'}

        :param user:  The Shotgun user entity dictionary that should be set on the copied context
        :returns: :class:`Context`
        """
        ctx_copy = copy.deepcopy(self)
        ctx_copy.__user = user
        return ctx_copy

    ################################################################################################
    # serialization

    def serialize(self, with_user_credentials=True):
        """
        Serializes the context into a string.

        Any Context object can be serialized to/deserialized from a string.
        This can be useful if you need to pass a Context between different processes.
        As an example, the ``tk-multi-launchapp`` uses this mechanism to pass the Context
        from the launch process (e.g. for example Shotgun Desktop) to the
        Application (e.g. Maya) being launched. Example:

            >>> import sgtk
            >>> tk = sgtk.sgtk_from_path("/studio.08/demo_project")
            >>> ctx = tk.context_from_path("/studio.08/demo_project/sequences/AAA/ABC/Lighting/dirk.gently/work")
            >>> context_str = ctx.serialize(ctx)
            >>> new_ctx = sgtk.Context.deserialize(context_str)

        :param with_user_credentials: If ``True``, the currently authenticated user's credentials, as
            returned by :meth:`sgtk.get_authenticated_user`, will also be serialized with the context.

        .. note:: For example, credentials should be omitted (``with_user_credentials=False``) when
            serializing the context from a user's current session to send it to a render farm. By doing
            so, invoking :meth:`sgtk.Context.deserialize` on the render farm will only restore the
            context and not the authenticated user.

        :returns: String representation
        """
        # Avoids cyclic imports
        from .api import get_authenticated_user

        data = {
            "project": self.project,
            "entity": self.entity,
            "user": self.user,
            "step": self.step,
            "task": self.task,
            "additional_entities": self.additional_entities,
            "source_entity": self.source_entity,
            "_pc_path": self.tank.pipeline_configuration.get_path()
        }

        if with_user_credentials:
            # If there is an authenticated user.
            user = get_authenticated_user()
            if user:
                # We should serialize it as well so that the next process knows who to
                # run as.
                data["_current_user"] = authentication.serialize_user(user)
        return pickle.dumps(data)

    @classmethod
    def deserialize(cls, context_str):
        """
        The inverse of :meth:`Context.serialize`.

        :param context_str: String representation of context, created with :meth:`Context.serialize`

        .. note:: If the context was serialized with the user credentials, the currently authenticated
            user will be updated with these credentials.

        :returns: :class:`Context`
        """
        # lazy load this to avoid cyclic dependencies
        from .api import Tank, set_authenticated_user

        try:
            data = pickle.loads(context_str)
        except Exception as e:
            raise TankContextDeserializationError(str(e))

        # first get the pipeline config path out of the dict
        pipeline_config_path = data["_pc_path"]
        del data["_pc_path"]

        # Authentication in Toolkit requires that credentials are passed from
        # one process to another so the currently authenticated user is carried
        # from one process to another. The current user needs to be part of the
        # context because multiple DCCs can run at the same time under different
        # users, e.g. launching Maya from the site as user A and Nuke from the tank
        # command as user B.
        user_string = data.get("_current_user")
        if user_string:
            # Remove it from the data
            del data["_current_user"]
            # and set the authenticated user user.
            user = authentication.deserialize_user(user_string)
            set_authenticated_user(user)

        # create a Sgtk API instance.
        tk = Tank(pipeline_config_path)

        # add it to the constructor instance
        data["tk"] = tk

        # and lastly make the obejct
        return cls(**data)

    ################################################################################################
    # private methods

    def _fields_from_entities(self, keys, entities):
        """
        """
        fields = {}

        for key in keys:

            # check each key to see if it has shotgun query information that we should resolve
            if key.shotgun_field_name:
                # this key is a shotgun value that needs fetching!

                # ensure that the context actually provides the desired entities
                if not key.shotgun_entity_type in entities:
                    continue

                entity = entities[key.shotgun_entity_type]
                entity_type = entity["type"]

                # Special handling of the name field since we normalize it
                sg_name = _get_entity_type_sg_name_field(entity_type)
                if key.shotgun_field_name == sg_name:
                    # already have the value cached - no need to fetch from shotgun
                    fields[key.name] = entity["name"]

                # Else create a field if we already have the key
                elif key.shotgun_field_name in entity:
                    fields[key.name] = entity[key.shotgun_field_name]

        return fields


    def _fields_from_shotgun(self, keys, entities):
        """
        Query Shotgun server for keys used by this template whose values come directly
        from Shotgun fields.

        :param keys: TemplateKeys to retrieve Shotgun fields for.
        :param entities: Dictionary of entities for the current context.

        :returns: Dictionary of field values extracted from Shotgun.
        :rtype: dict

        :raises TankError: Raised if a key is missing from the entities list when ``validate`` is ``True``.
        """
        fields = {}
        # for any sg query field
        for key in keys:

            # check each key to see if it has shotgun query information that we should resolve
            if key.shotgun_field_name:
                # this key is a shotgun value that needs fetching!

                # ensure that the context actually provides the desired entities
                if not key.shotgun_entity_type in entities:
                        continue

                entity = entities[key.shotgun_entity_type]

                # check the context cache
                cache_key = (entity["type"], entity["id"], key.shotgun_field_name)
                if cache_key in self._entity_fields_cache:
                    # already have the value cached - no need to fetch from shotgun
                    fields[key.name] = self._entity_fields_cache[cache_key]

                else:
                    # get the value from shotgun
                    filters = [["id", "is", entity["id"]]]
                    query_fields = [key.shotgun_field_name]
                    result = self.__tk.shotgun.find_one(key.shotgun_entity_type, filters, query_fields)
                    if not result:
                        # no record with that id in shotgun!
                        raise TankError("Could not retrieve Shotgun data for key '%s'. "
                                        "No records in Shotgun are matching "
                                        "entity '%s' (Which is part of the current "
                                        "context '%s')" % (key, entity, self))

                    value = result.get(key.shotgun_field_name)

                    # note! It is perfectly possible (and may be valid) to return None values from
                    # shotgun at this point. In these cases, a None field will be returned in the
                    # fields dictionary from as_template_fields, and this may be injected into
                    # a template with optional fields.

                    if value is None:
                        processed_val = None

                    else:

                        # now convert the shotgun value to a string.
                        # note! This means that there is no way currently to create an int key
                        # in a tank template which matches an int field in shotgun, since we are
                        # force converting everything into strings...

                        processed_val = shotgun_entity.sg_entity_to_string(self.__tk,
                                                                           key.shotgun_entity_type,
                                                                           entity.get("id"),
                                                                           key.shotgun_field_name,
                                                                           value)

                        if not key.validate(processed_val):
                            raise TankError("Template validation failed for value '%s'. This "
                                            "value was retrieved from entity %s in Shotgun to "
                                            "represent key '%s'." % (processed_val, entity, key))

                    # all good!
                    # populate dictionary and cache
                    fields[key.name] = processed_val
                    self._entity_fields_cache[cache_key] = processed_val


        return fields


    def _fields_from_entity_paths(self, template):
        """
        Determines a template's key values based on context by walking up the context entities paths until
        matches for the template are found.

        :param template:    The template to find fields for
        :returns:           A dictionary of field name, value pairs for any fields found for the template
        """
        fields = {}
        project_roots = self.__tk.pipeline_configuration.get_data_roots().values()

        # get all locations on disk for our context object from the path cache
        path_cache_locations = self.entity_locations

        # now loop over all those locations and check if one of the locations
        # are matching the template that is passed in. In that case, try to
        # extract the fields values.
        for cur_path in path_cache_locations:

            # walk up path until we reach the project root and get values
            while cur_path not in project_roots:
                cur_fields = template.validate_and_get_fields(cur_path)
                if cur_fields is not None:
                    # If there are conflicts, there is ambiguity in the schema
                    for key, value in cur_fields.items():
                        if value != fields.get(key, value):
                            # Value is ambiguous for this key
                            cur_fields[key] = None
                    fields.update(cur_fields)
                    break
                else:
                    cur_path = os.path.dirname(cur_path)

        return fields

    def _fields_from_template_tree(self, template, known_fields, context_entities):
        """
        Determines values for a template's keys based on the context by walking down the template tree
        matching template keys with entity types.

        This method attempts to find as many fields as possible from the path cache but will try to ensure
        that incorrect fields are never returned, even if the path cache is not 100% clean (e.g. contains
        out-of-date paths for one or more of the entities in the context).

        :param template:            The template to find fields for
        :param known_fields:        Dictionary of fields that are already known for this template.  The
                                    logic in this method will ensure that any fields found match these.
        :param context_entities:    A dictionary of {entity_type:entity_dict} that contains all the entities
                                    belonging to this context.
        :returns:                   A dictionary of all fields found by this method
        """
        # Step 1 - Walk up the template tree and collect templates
        #
        # Use cached paths to find field values
        # these will be returned in top-down order:
        # [<Sgtk TemplatePath sequences/{Sequence}>,
        #  <Sgtk TemplatePath sequences/{Sequence}/{Shot}>,
        #  <Sgtk TemplatePath sequences/{Sequence}/{Shot}/{Step}>,
        #  <Sgtk TemplatePath sequences/{Sequence}/{Shot}/{Step}/publish>,
        #  <Sgtk TemplatePath sequences/{Sequence}/{Shot}/{Step}/publish/maya>,
        #  <Sgtk TemplatePath maya_shot_publish: sequences/{Sequence}/{Shot}/{Step}/publish/maya/{name}.v{version}.ma>]
        templates = _get_template_ancestors(template)

        # Step 2 - walk templates from the root down.
        # for each template, get all paths we have stored in the database and find any fields we can for it, making
        # sure that none of the found fields conflict with the list of entities provided to this method
        #
        # build up a list of fields as we go so that each level matches
        # at least the fields from all previous levels
        found_fields = {}

        # get a path cache handle
        path_cache = PathCache(self.__tk)
        try:
            for template in templates:
                # iterate over all keys in the {key_name:key} dictionary for the template
                # looking for any that represent context entities (key name == entity type)
                template_key_dict = template.keys
                for key_name in template_key_dict.keys():
                    # Check to see if we already have a value for this key:
                    if key_name in known_fields or key_name in found_fields:
                        # already have a value so skip
                        continue

                    if key_name not in context_entities:
                        # key doesn't represent an entity so skip
                        continue

                    # find fields for any paths associated with this entity by looking in the path cache:
                    entity_fields = _values_from_path_cache(context_entities[key_name], template, path_cache,
                                                           required_fields=found_fields)

                    # entity_fields may contain additional fields that correspond to entities
                    # so we should be sure to validate these as well if we can.
                    #
                    # The following example illustrates where the code could previously return incorrect entity
                    # information from this method:
                    #
                    # With the following template:
                    #    /{Sequence}/{Shot}/{Step}
                    #
                    # And a path cache that contains:
                    #    Type     | Id  | Name     | Path
                    #    ----------------------------------------------------
                    #    Sequence | 001 | Seq_001  | /Seq_001
                    #    Shot     | 002 | Shot_A   | /Seq_001/Shot_A
                    #    Step     | 003 | Lighting | /Seq_001/Shot_A/Lighting
                    #    Step     | 003 | Lighting | /Seq_001/blah/Shot_B/Lighting   <- this is out of date!
                    #    Shot     | 004 | Shot_B   | /Seq_001/blah/Shot_B            <- this is out of date!
                    #
                    # (Note: the schema/templates have been changed since the entries for Shot_b were added)
                    #
                    # The sub-templates used to search for fields are:
                    #    /{Sequence}
                    #    /{Sequence}/{Shot}
                    #    /{Sequence}/{Shot}/{Step}
                    #
                    # And the entities passed into the method are:
                    #    Sequence:   Seq_001
                    #    Shot:       Shot_B
                    #    Step:       Lighting
                    #
                    # We are searching for fields for 'Shot_B' that has a broken entry in the path cache so the fields
                    # returned for each level of the template will be:
                    #    /{Sequence}                 -> {"Sequence":"Seq_001"} <- Correct
                    #    /{Sequence}/{Shot}          -> {}                     <- entry not found for Shot_B matching
                    #                                                             the template
                    #    /{Sequence}/{Shot}/{Step}   -> {"Sequence":"Seq_001", <- Correct
                    #                                    "Shot":"Shot_A",      <- Wrong!
                    #                                    "Step":"Lighting"}    <- Correct
                    #
                    # In previous implementations, the final fields would incorrectly be returned as:
                    #
                    #     {"Sequence":"Seq_001",
                    #      "Shot":"Shot_A",
                    #      "Step":"Lighting"}
                    #
                    # The wrong Shot (Shot_A) is returned and not caught because the code only tested that the Step
                    # entity matches and just assumes that the rest is correct - this isn't the case when there is
                    # a one-to-many relationship between entities!
                    #
                    # Therefore, we need to validate that we didn't find any entity fields that we should have found
                    # previously/higher up in the template definition.  If we did then the entries that were found
                    # may not be correct so we have to discard them!
                    found_mismatching_field = False
                    for field_name, field_value in entity_fields.iteritems():
                        if field_name in known_fields:
                            # We found a field we already knew about...
                            if field_value != known_fields[field_name]:
                                # ...but it doesn't match!
                                found_mismatching_field = True
                        elif field_name in found_fields:
                            # We found a field we found before...
                            if field_value != found_fields[field_name]:
                                # ...but it doesn't match!
                                found_mismatching_field = True
                        elif field_name == key_name:
                            # We found a field that matches the entity we were searching for so it must be valid!
                            found_fields[field_name] = field_value
                        elif field_name in context_entities:
                            # We found an entity type that we should have found before (in a previous/shorter
                            # template).  This means we can't trust any other fields that were found as they
                            # may belong to a completely different entity/path!
                            found_mismatching_field = True

                    if not found_mismatching_field:
                        # all fields are ok so we can add them all to the list of found fields :)
                        found_fields.update(entity_fields)

        finally:
            path_cache.close()

        return found_fields


################################################################################################
# factory methods for constructing new Context objects, primarily called from the Tank object

def create_empty(tk):
    """
    Constructs an empty context.

    :returns: a context object
    """
    return Context(tk)


def from_path(tk, path, previous_context=None):
    """
    Factory method that constructs a context object from a path on disk.

    The algorithm will navigate upwards in the file system and collect
    as much tank metadata as possible to construct a Tank context.

    :param path: a file system path
    :param previous_context: A context object to use to try to automatically extend the generated
                             context if it is incomplete when extracted from the path. For example,
                             the Task may be carried across from the previous context if it is
                             suitable and if the task wasn't already expressed in the file system
                             path passed in via the path argument.
    :type previous_context: :class:`Context`
    :returns: :class:`Context`
    """
    entity_dict = _build_entity_dict_from_path(tk, path)
    if not entity_dict:
        raise TankError("Cannot get entity in path_cache for path: %s" % path)

    # Pass along the entity to be processed by from_entity_dictionary()
    log.debug("Running context_from_path: %s" % path)
    return _from_entity_dictionary(tk, entity_dict, previous_context)


def from_entity(tk, entity_type, entity_id, previous_context=None):
    """
    Constructs a context from a shotgun entity.

    For more information, see :meth:`Sgtk.context_from_entity`.

    :param tk:           Sgtk API handle
    :param entity_type:  The shotgun entity type to produce a context for
    :param entity_id:    The shotgun entity id to produce a context for
    :param previous_context: A context object to use to try to automatically extend the generated
                             context if it is incomplete when extracted from the path. For example,
                             the Task may be carried across from the previous context if it is
                             suitable and if the task wasn't already expressed in the file system
                             path passed in via the path argument.
    :type previous_context: :class:`Context`
    :returns: :class:`Context`
    """
    entity_dict = {"type": entity_type, "id": entity_id }

    # Pass along the entity to be processed by from_entity_dictionary()
    log.debug("Running context_from_entity: %s" % pprint.pformat(entity_dict))
    return _from_entity_dictionary(tk, entity_dict, previous_context)


def from_entity_dictionary(tk, entity_dict, previous_context=None):
    """
    Constructs a context from a shotgun entity dictionary.

    For more information, see :meth:`Sgtk.context_from_entity_dictionary`.

    :param tk: :class:`Sgtk`
    :param dict entity_dictionary: The entity dictionary to create the context from
        containing at least: {"type":entity_type, "id":entity_id}
    :param previous_context: A context object to use to try to automatically extend the generated
                             context if it is incomplete when extracted from the path. For example,
                             the Task may be carried across from the previous context if it is
                             suitable and if the task wasn't already expressed in the file system
                             path passed in via the path argument.
    :type previous_context: :class:`Context`
    :returns: :class:`Context`
    """
    # Pass along the entity_dict to be processed by from_entity_dictionary()
    log.debug("Running context_from_entity_dictionary: %s" % pprint.pformat(entity_dict))
    return _from_entity_dictionary(tk, entity_dict, previous_context)


def _from_entity_dictionary(tk, entity_dict, previous_context=None):
    """
    """
    # Get a context-valid entity dictionary
    entity_dict = _get_valid_entity_dict(tk, entity_dict)

    # Embed the entity in the appropriate field
    entity_type = entity_dict.get("type")
    if entity_type == "Project":
        entity_dict["project"] = _build_clean_entity(tk, entity_dict)
    elif entity_type == "Task":
        entity_dict["task"] = _build_clean_entity(tk, entity_dict)
    else:
        entity_dict["entity"] = _build_clean_entity(tk, entity_dict)

    # Initialize the new context dictionary
    context_dict = {
        "tk":                   tk,
        "project":              entity_dict.get("project"),
        "entity":               entity_dict.get("entity"),
        "step":                 entity_dict.get("step"),
        "user":                 entity_dict.get("user"),
        "task":                 entity_dict.get("task"),
        "source_entity":        entity_dict.get("source_entity"),
        "additional_entities":  entity_dict.get("additional_entities") or []
    }

    # See if we can populate any missing fields from the previous context
    if previous_context and \
       context_dict.get("entity") == previous_context.entity and \
       context_dict.get("additional_entities") == previous_context.additional_entities:

        # cool, everything is matching down to the step/task level.
        # if context is missing a step and a task, we try to auto populate it.
        # (note: weird edge that a context can have a task but no step)
        if context_dict.get("task") is None and context_dict.get("step") is None:
            context_dict["step"] = previous_context.step

        # now try to assign previous task but only if the step matches!
        if context_dict.get("task") is None and context_dict.get("step") == previous_context.step:
            context_dict["task"] = previous_context.task

    log.debug("Building context:\n%s" % pprint.pformat(context_dict))
    return Context(**context_dict)


################################################################################################
# serialization

def serialize(context):
    """
    Serializes the context into a string.

    .. deprecated:: v0.18.12
       Use :meth:`Context.serialize`
    """
    return context.serialize()


def deserialize(context_str):
    """
    The inverse of :meth:`serialize`.

    .. deprecated:: v0.18.12
       Use :meth:`Context.deserialize`
    """
    return Context.deserialize(context_str)


################################################################################################
# YAML representer/constructor

def context_yaml_representer(dumper, context):
    """
    Custom serializer.
    Creates yaml code for a context object.

    Legacy, kept for compatibility reasons, can probably be removed at this point.

    .. note:: Contrary to :meth:`sgtk.Context.serialize`, this method doesn't serialize the
        currently authenticated user.
    """

    # first get the stuff which represents all the Context()
    # constructor parameters
    context_dict = {
        "project": context.project,
        "entity": context.entity,
        "user": context.user,
        "step": context.step,
        "task": context.task,
        "additional_entities": context.additional_entities
    }

    # now we also need to pass a TK instance to the constructor when we
    # are deserializing the object. For this purpose, pass a
    # pipeline config path as part of the dict
    context_dict["_pc_path"] = context.tank.pipeline_configuration.get_path()

    return dumper.represent_mapping(u'!TankContext', context_dict)


def context_yaml_constructor(loader, node):
    """
    Custom deserializer.
    Constructs a context object given the yaml data provided.

    Legacy, kept for compatibility reasons, can probably be removed at this point.

    .. note:: Contrary to :meth:`sgtk.Context.deserialize`, this method doesn't can't restore the
        currently authenticated user.
    """
    # lazy load this to avoid cyclic dependencies
    from .api import Tank

    # get the dict from yaml
    context_constructor_dict = loader.construct_mapping(node)

    # first get the pipeline config path out of the dict
    pipeline_config_path = context_constructor_dict["_pc_path"]
    del context_constructor_dict["_pc_path"]

    # create a Sgtk API instance.
    tk = Tank(pipeline_config_path)

    # add it to the constructor instance
    context_constructor_dict["tk"] = tk

    # and lastly make the obejct
    return Context(**context_constructor_dict)

yaml.add_representer(Context, context_yaml_representer)
yaml.add_constructor(u'!TankContext', context_yaml_constructor)


################################################################################################
# utility methods

def _get_entity_type_sg_name_field(entity_type):
    """
    Return the Shotgun name field to use for the specified entity type.  This
    is needed as not all entity types are consistent!

    :param entity_type:     The entity type to get the name field for
    :returns:               The name field for the specified entity type
    """
    return {
        "HumanUser": "name",
        "Task":      "content",
        "Project":   "name"
    }.get(entity_type, "code")


def _get_templatekey_sg_fields(tk, entity_type):
    """
    """
    fields = []

    # Get any Shotgun template keys that match this entity type
    for key in tk.template_keys.values():
        if not key.shotgun_field_name or not key.shotgun_entity_type:
            continue

        if entity_type == key.shotgun_entity_type:
            fields.append(key.shotgun_field_name)

    return fields


def _get_entity_name(entity_dict):
    """
    Extract the entity name from the specified entity dictionary if it can
    be found.  The entity dictionary must contain at least 'type'

    :param entity_dict:   An entity dictionary to extract the name from
    :returns:             The name of the entity if found in the entity
                          dictionary, otherwise None
    """
    name_field = _get_entity_type_sg_name_field(entity_dict["type"])
    entity_name = entity_dict.get(name_field)
    if entity_name == None:
        # Also check to see if entity contains 'name':
        if name_field != "name":
            entity_name = entity_dict.get("name")
    return entity_name


def _build_clean_entity(tk, ent):
    """
    Ensure entity has id, type and name fields and build a clean
    entity dictionary containing just those fields to return, stripping
    out all other fields.

    :param ent: The entity dictionary to build a clean dictionary from
    :returns:   A clean entity dictionary containing just 'type', 'id'
               and 'name' if all three exist in the input dictionary
               or None if they don't.
    """
    # basic sanity check
    if not ent:
        return None

    ent_id = ent.get("id")
    ent_type = ent.get("type")

    # make sure we have id and type
    if not ent_id or not ent_type:
       return None

    # make sure we have name
    ent_name = _get_entity_name(ent)
    if not ent_name:
       return None

    new_ent = {
        "id":   ent_id,
        "type": ent_type,
        "name": ent_name
    }

    # Get any Shotgun template keys and store any existing fields of interest
    fields = _get_templatekey_sg_fields(tk, ent_type)
    for field in fields:
        if field in ent:
            new_ent[field] = ent[field]

    # return a clean dictionary:
    return new_ent


def _process_entity(curr_entity, entity_dict, required_fields, additional_types=None):
    """
    """
    fields_to_types = {
        "project":      "Project",
        "step":         "Step",
        "task":         "Task",
        "user":         "HumanUser",
        "sg_sequence":  "Sequence",
        "sg_shot":      "Shot"
    }

    required_fields = required_fields or fields_to_types.keys()
    additional_types = additional_types or []

    curr_type = curr_entity["type"]

    # Treat the "entity" field special, since it is positional
    if "entity" in required_fields and not entity_dict.get("entity"):
        # None of these can be the "entity"
        if curr_type not in ("project", "step", "task", "user"):
            # The first entity to match the criteria is the "entity"
            entity_dict["entity"] = curr_entity
            return

    # Go through the rest of the required fields and see if we can find
    # an entity that matches the field type
    for field_name in required_fields:

        # If we have an entity, format the entity_type field
        parent_entity = entity_dict.get("entity")
        if parent_entity:
            field_name = field_name.format(entity_type=parent_entity["type"])

        # Just take the last part of hierarchical fields
        lookup_field = field_name.split(".")[-1]

        # If we have a mapping for this field and the entity type matches...
        if lookup_field in fields_to_types and curr_type == fields_to_types[lookup_field]:

            # Error out if we've populated this field before and the previous
            # value is different than the current value
            prev_entity = entity_dict.get(field_name)
            if prev_entity and curr_entity["id"] != prev_entity["id"]:
                raise TankError("Context entity has two conflicting values for field '%s'."
                    "\n\t%s\n\t%s" % (field_name, curr_entity, prev_entity))

            # Populate the corresponding field in the entity dictionary
            entity_dict[field_name] = curr_entity

    # If the entity type matches a type defined in additional types,
    # add it to the additional_entities dict
    if curr_type in additional_types:
        if "additional_entities" not in entity_dict:
            entity_dict["additional_entities"] = []
        entity_dict["additional_entities"].append(curr_entity)


def _build_entity_dict_from_path(tk, path, required_fields=None, additional_types=None):
    """
    """
    entity_dict = {}

    # ask hook for extra entity types we should recognize and insert into the additional_entities list.
    if not additional_types:
        additional_types = tk.execute_core_hook("context_additional_entities").get("entity_types_in_path", [])

    # We're going to use the path cache to get all entities for the path
    path_cache = PathCache(tk)

    # Grab all project roots
    project_roots = tk.pipeline_configuration.get_data_roots().values()

    # note - paths returned by get_paths are always prefixed with a
    # project root so there is no risk we end up with an infinite loop here..
    try:
        curr_path = path
        while True:
            curr_entity = path_cache.get_entity(curr_path)
            if curr_entity:
                # The first valid element processed (the last one in the path) is the primary entity
                # HumanUser and Step entities cannot be primary entities
                if not entity_dict.get("type") and curr_entity["type"] not in ("HumanUser", "Step"):
                    entity_dict.update(curr_entity)

                # Else, organize it in the entity dictionary
                else:
                    _process_entity(curr_entity, entity_dict, required_fields, additional_types)

            # Now process any secondary entities
            for sec_entity in path_cache.get_secondary_entities(curr_path):
                _process_entity(sec_entity, entity_dict, required_fields, additional_types)

            if curr_path in project_roots:
                break

            # Move up to the next level directory and repeat
            curr_path = os.path.dirname(curr_path)

    finally:
        path_cache.close()

    return entity_dict


def _get_valid_entity_dict(tk, entity_dict):
    """
    """
    # Basic sanity check
    if not isinstance(entity_dict, dict):
        raise TankError("Cannot create a context from an empty or invalid entity dictionary!")

    # Since we are modifying in place, make a copy
    entity_dict = copy.deepcopy(entity_dict)

    # Ensure we have a type and id
    entity_type = entity_dict.get("type")
    entity_id   = entity_dict.get("id")

    if not entity_type:
        raise TankError("Cannot create a context without an entity type!")
    if not entity_id:
        raise TankError("Cannot create a context without an entity id!")

    # Sanitize name
    name_field = _get_entity_type_sg_name_field(entity_type)
    if name_field in entity_dict:
        entity_dict["name"] = entity_dict.pop(name_field)

    # Special case handling for published file entities
    if entity_type in ["PublishedFile", "TankPublishedFile"]:

        # If we are missing all required fields, go get them
        required_fields = ["task", "entity", "project"]
        if all([not entity_dict.get(x) for x in required_fields]):
            entity_dict = _build_entity_dict(tk, entity_dict, required_fields)

        # Iterate (in order) over entity fields to get the new entity to process
        for field in required_fields:
            new_entity = _build_clean_entity(tk, entity_dict.get(field))
            if new_entity:

                # Add the original entity as the source entity
                new_entity["source_entity"] = _build_clean_entity(tk, entity_dict)

                # Rerun context creation with new primary entity
                return _get_valid_entity_dict(tk, new_entity)

        # If we got here, we don't have a valid entity dictionary
        raise TankError("'%s' entity missing required fields: %s" %
                (entity_type, pprint.pformat(required_fields)))

    # We have 3 valid types of primary entities: 
    # Project, Task, or Entity (Shot, Sequence, Asset, etc)
    if entity_type == "Project":
        required_fields = ["name"]
        optional_fields = []
        optional_fields += tk.execute_core_hook("context_additional_entities").get("entity_fields_on_project", [])

    elif entity_type == "Task":
        required_fields = ["name", "step", "entity", "project"]
        optional_fields = ["entity.{entity_type}.sg_shot", "entity.{entity_type}.sg_sequence"]
        optional_fields += tk.execute_core_hook("context_additional_entities").get("entity_fields_on_task", [])            

        # If we have an entity, format the entity_type fields 
        parent_entity = entity_dict.get("entity")
        if parent_entity:
            optional_fields = [field.format(entity_type=parent_entity["type"]) for field in optional_fields]

    else:
        required_fields = ["name", "project"]
        optional_fields = ["sg_sequence", "sg_shot"]
        optional_fields += tk.execute_core_hook("context_additional_entities").get("entity_fields_on_entity", [])

    # If we are missing any required or optional fields, attempt to go get them
    entity_dict = _build_entity_dict(tk, entity_dict, required_fields + optional_fields)

    # If we're missing any required fields, we're not a valid entity dictionary
    missing_fields = list(set(required_fields) - set([k for k, v in entity_dict.items() if v]))
    if missing_fields:
        raise TankError("'%s' entity missing required fields: %s" %
                (entity_type, pprint.pformat(missing_fields)))

    # Add any entities defined in additional_fields
    for field in optional_fields:
        # Make sure to format the entity_type field
        parent_entity = entity_dict.get("entity")
        if parent_entity:
            parent_type = parent_entity["type"]
            field = field.format(entity_type=parent_type)

        additional_entity = _build_clean_entity(tk, entity_dict.get(field))
        if additional_entity:
            if "additional_entities" not in entity_dict:
                entity_dict["additional_entities"] = []
            entity_dict["additional_entities"].append(additional_entity)

    # Remove duplicates from additional_entities list
    if "additional_entities" in entity_dict:
        entity_dict["additional_entities"] = dict([(x["type"], x) for x in entity_dict["additional_entities"]]).values()

    return entity_dict


def _build_entity_dict(tk, entity_dict, required_fields=None):
    """
    """
    entity_dict = copy.deepcopy(entity_dict)
    required_fields = required_fields or []

    # Get the list of missing fields
    missing_fields = list(set(required_fields) - set([k for k, v in entity_dict.items() if v]))
    if not missing_fields:
        # We have all required fields, so return
        return entity_dict

    # Attempt to get missing fields from the path cache
    entity_dict = _get_entity_dict_from_path_cache(tk, entity_dict, missing_fields)

    # Get the list of missing fields
    missing_fields = list(set(required_fields) - set([k for k, v in entity_dict.items() if v]))
    if not missing_fields:
        # We have all required fields, so return
        return entity_dict

#    # Attempt to get missing fields from the folder schema
#    entity_dict = _get_entity_dict_from_folder_schema(tk, entity_dict, missing_fields)
#
#    # Get the list of missing fields
#    missing_fields = list(set(required_fields) - set([k for k, v in entity_dict.items() if v]))
#    if not missing_fields:
#        # We have all required fields, so return
#        return entity_dict

    # Attempt to get missing fields from shotgun
    entity_dict = _get_entity_dict_from_shotgun(tk, entity_dict, missing_fields)

    # Get the list of missing fields
    missing_fields = list(set(required_fields) - set([k for k, v in entity_dict.items() if v]))
    if not missing_fields:
        # We have all required fields, so return
        return entity_dict

    # Attempt to get missing fields from parent entity
    # Note: at the moment tasks aren't stored in the path_cache, so entity.* fields
    # will almost always be empty. Attempt to populate them from the parent entity
    parent_entity = entity_dict.get("entity")
    if parent_entity:
        parent_type = parent_entity["type"]
        missing_fields = [field.format(entity_type=parent_type) for field in missing_fields]

        # Put the missing entity.* fields into the correct namespace
        parent_fields = []
        for field in missing_fields:
            match = re.search("^entity\.%s\.(\S+)$" % parent_type, field)
            if match:
                parent_fields.append(match.group(1))

        # Recurse to get the valid entity dict (hopefully from path_cache)
        parent_entity = _build_entity_dict(tk, parent_entity, parent_fields)

        # Populate the correct field on the task
        for key in parent_entity.keys():
            field = "entity.%s.%s" % (parent_type, key)
            if field in missing_fields:
                entity_dict[field] = parent_entity[key]

    # Regardless of outcome, return the processed entity_dict
    return entity_dict


def _get_entity_dict_from_path_cache(tk, entity_dict, required_fields):
    """
    """
    entity_dict = copy.deepcopy(entity_dict)

    entity_id   = entity_dict["id"]
    entity_type = entity_dict["type"]

    # We're going to use the path cache to get paths for the entity
    path_cache = PathCache(tk)

    try:
        paths = path_cache.get_paths(entity_type, entity_id, primary_only=True)
        for path in paths:

            # Get the entity for each path
            path_entity = path_cache.get_entity(path)

            # The id should always match
            if not path_entity or path_entity.get("id") != entity_id:
                # this is some sort of anomaly! the path returned by get_paths
                # does not resolve in get_entity. This can happen if the storage
                # mappings are not consistent or if there is not a 1 to 1 relationship
                #
                # This can also happen if there are extra slashes at the end of the path
                # in the local storage defs and in the pipeline_configuration.yml file.
                raise TankError("The path '%s' associated with %s id %s does not "
                                "resolve correctly. This may be an indication of an issue "
                                "with the local storage setup. Please contact %s."
                                % (curr_path, entity_type, entity_id, constants.SUPPORT_EMAIL))

            # If all we were looking for was type, id, and name, then we're done
            if all([path_entity.get(x) for x in required_fields]):
                return path_entity

            # Accumulate information about the entity from all relevant path_cache entries
            new_entity_dict = _build_entity_dict_from_path(tk, path, required_fields, [])
            for key in new_entity_dict.keys():
                if key in entity_dict and entity_dict[key] != new_entity_dict[key]:
                    raise TankError("Context entity has two conflicting values for field '%s'."
                        "\n\t%s\n\t%s" % (key, entity_dict, new_entity_dict))

                entity_dict[key] = new_entity_dict[key]

            # Optimization: check to see if we've found what we need, and if so exit
            if all([entity_dict.get(x) for x in required_fields]):
                return entity_dict

    finally:
        path_cache.close()

    return entity_dict

def _get_entity_dict_from_folder_schema(tk, entity_dict, required_fields):
    """
    """
    entity_dict = copy.deepcopy(entity_dict)

    entity_id   = entity_dict["id"]
    entity_type = entity_dict["type"]
    
    sg_data = {entity_type: entity_dict}

    # Get matching folder objs and extract sg data from them
    folder_objs = tk.folder_config.get_folder_objs_for_entity_type(entity_type)
    for folder_obj in folder_objs:
        new_data = folder_obj.extract_shotgun_data_upwards(tk.shotgun, sg_data)
        for entity in new_data.values():
            _process_entity(entity, entity_dict, required_fields)

        # Add new data to sg_data for next iteration
        sg_data = new_data

        # Optimization: check to see if we've found what we need, and if so exit
        if all([entity_dict.get(x) for x in required_fields]):
            return entity_dict

    return entity_dict


def _get_entity_dict_from_shotgun(tk, entity_dict, required_fields):
    """
    """
    entity_dict = copy.deepcopy(entity_dict)

    entity_id   = entity_dict["id"]
    entity_type = entity_dict["type"]

    name_field = _get_entity_type_sg_name_field(entity_type)
    key_fields = _get_templatekey_sg_fields(tk, entity_type)
    data = tk.shotgun.find_one(entity_type, [["id", "is", entity_id]], required_fields + key_fields + [name_field])
    if not data:
        raise TankError("Cannot find %s Entity: '%s' in Shotgun." % (entity_type, entity_id))

    # Sanitize the name field
    data["name"] = data.pop(name_field)

    for key in data.keys():
        if key in entity_dict and entity_dict[key] != data[key]:
            raise TankError("Context entity has two conflicting values for field '%s'."
                "\n\t%s\n\t%s" % (key, entity_dict, data))

        # Update the original entity_dictionary
        entity_dict[key] = data[key]

    return entity_dict


def _values_from_path_cache(entity, cur_template, path_cache, required_fields):
    """
    Determine values for template fields based on an entities cached paths.

    :param entity:          The entity to search for fields for
    :param cur_template:    The template to use to search the path cache
    :path_cache:            An instance of the path_cache to search in
    :param required_fields: A list of fields that must exist in any matched path
    :return:                Dictionary of fields found by matching the template against all paths
                            found for the entity
    """

    # use the databsae to go from shotgun type/id --> paths
    entity_paths = path_cache.get_paths(entity["type"], entity["id"], primary_only=True)

    # Mapping for field values found in conjunction with this entities paths
    unique_fields = {}
    # keys whose values should be removed from return values
    remove_keys = set()

    for path in entity_paths:

        # validate path and get fields:
        path_fields = cur_template.validate_and_get_fields(path, required_fields = required_fields)
        if not path_fields:
            continue

        # Check values against those found for other paths
        for key, value in path_fields.items():
            if key in unique_fields and value != unique_fields[key]:
                # value for this key isn't unique!
                if key == entity["type"]:
                    # Ambiguity for Entity key
                    # now it is possible that we have ambiguity here, but it is normally
                    # an edge case. For example imagine that an asset has paths
                    # /proj/hero_HIGH
                    # /proj/hero_LOW
                    # and we are mapping against template /%(Project)s/%(Asset)s
                    # both paths are valid matches, so we have ambiguous state for the entity
                    msg = "Ambiguous data. Multiple paths cached for %s which match template %s"
                    raise TankError(msg % (str(entity), str(cur_template)))
                else:
                    # ambiguity for Static key
                    unique_fields[key] = None
                    remove_keys.add(key)

            else:
                unique_fields[key] = value

    # we want to remove the None/ambiguous values so they don't interfere with other entities
    for remove_key in remove_keys:
        del(unique_fields[remove_key])

    return unique_fields


def _get_template_ancestors(template):
    """Return templates branch of the template tree, ordered from first template
    below the project root down to and including the input template.
    """
    # TODO this would probably be better as the Template's responsibility
    templates = [template]
    cur_template = template
    while cur_template.parent is not None and len(cur_template.parent.keys) > 0:
        next_template = cur_template.parent
        templates.insert(0, next_template)
        cur_template = next_template
    return templates
