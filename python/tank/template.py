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
Management of file and directory templates.

"""

import os
import re
import sys
import copy

from . import templatekey
from . import constants
from .errors import TankError
from .template_path_parser import TemplatePathParser
from .util import shotgun, shotgun_entity
from . import LogManager

log = LogManager.get_logger(__name__)

class Template(object):
    """
    Represents an expression containing several dynamic tokens
    in the form of :class:`TemplateKey` objects.
    """

    @classmethod
    def _keys_from_definition(cls, definition, template_name, keys):
        """Extracts Template Keys from a definition.

        :param definition: Template definition as string
        :param template_name: Name of template.
        :param keys: Mapping of key names to keys as dict

        :returns: Mapping of key names to keys and collection of keys ordered as they appear in the definition.
        :rtype: List of Dictionaries, List of lists
        """
        names_keys = {}
        ordered_keys = []
        # regular expression to find key names
        regex = r"(?<={)%s(?=})" % constants.TEMPLATE_KEY_NAME_REGEX
        key_names = re.findall(regex, definition)
        for key_name in key_names:
            key = keys.get(key_name)
            if key is None:
                msg = "Template definition for template %s refers to key {%s}, which does not appear in supplied keys."
                raise TankError(msg % (template_name, key_name))
            else:
                if names_keys.get(key.name, key) != key:
                    # Different keys using same name
                    msg = ("Template definition for template %s uses two keys" +
                           " which use the name '%s'.")
                    raise TankError(msg % (template_name, key.name))
                names_keys[key.name] = key
                ordered_keys.append(key)
        return names_keys, ordered_keys

    def __init__(self, definition, keys, pipeline_configuration, name=None):
        """
        This class is not designed to be used directly but
        should be subclassed by any Template implementations.

        Current implementations can be found in
        the :class:`TemplatePath` and :class:`TemplateString` classes.

        :param definition: Template definition.
        :type definition: String
        :param keys: Mapping of key names to keys
        :type keys: Dictionary
        :param pipeline_configuration: The associated PipelineConfiguration object this belongs to.
        :param name: (Optional) name for this template.
        :type name: String
        """
        self._name = name
        self._pipeline_configuration = pipeline_configuration
        self._entity_fields_cache = {}

        # version for __repr__
        self._repr_def = self._fix_key_names(definition, keys)

        variations = self._definition_variations(definition)
        # We want them most inclusive(longest) version first
        variations.sort(key=lambda x: len(x), reverse=True)

        # get format keys and types
        self._keys = []
        self._ordered_keys = []
        for variation in variations:
            var_keys, ordered_keys = self._keys_from_definition(variation, name, keys)
            self._keys.append(var_keys)
            self._ordered_keys.append(ordered_keys)

        # substitute aliased key names
        self._definitions = []
        for variation in variations:
            self._definitions.append(self._fix_key_names(variation, keys))

        # get definition ready for string substitution
        self._cleaned_definitions = []
        for definition in self._definitions:
            self._cleaned_definitions.append(self._clean_definition(definition))

        # string which will be prefixed to definition
        self._prefix = ''
        self._static_tokens = []

    def __repr__(self):
        class_name = self.__class__.__name__
        if self.name:
            return "<Sgtk %s %s: %s>" % (class_name, self.name, self._repr_def)
        else:
            return "<Sgtk %s %s>" % (class_name, self._repr_def)

    def __str__(self):
        return self._definitions[0]

    @property
    def name(self):
        """
        The Template name attribute
        """
        return self._name

    @property
    def pipeline_configuration(self):
        """
        The associated PipelineConfiguration object this Template belongs to.
        """
        return self._pipeline_configuration

    @property
    def definition(self):
        """
        The template as a string, e.g ``shots/{Shot}/{Step}/pub/{name}.v{version}.ma``
        """
        # Use first definition as it should be most inclusive in case of variations
        return self._definitions[0]

    @property
    def static_tokens(self):
        """
        A list of static tokens for the first definition
        as it should be the most inclusive in case of variations

        :returns: a list of strings
        """
        return [y for x in self._static_tokens[0] for y in x.split(self._token) if y]

    @property
    def keys(self):
        """
        The keys that this template is using. For a template
        ``shots/{Shot}/{Step}/pub/{name}.v{version}.ma``, the keys are ``{Shot}``,
        ``{Step}`` and ``{name}``.

        :returns: a dictionary of class:`TemplateKey` objects, keyed by token name.
        """
        # First keys should be most inclusive
        return self._keys[0].copy()

    def is_optional(self, key_name):
        """
        Returns true if the given key name is optional for this template.

        For the template ``{Shot}[_{name}]``,
        ``is_optional("Shot")`` would return ``False`` and ``is_optional("name")``
        would return ``True``

        :param key_name: Name of template key for which the check should be carried out
        :returns: True if key is optional, False if not.
        """
        # the key is required if it's in the
        # minimum set of keys for this template
        if key_name in min(self._keys):
            # this key is required
            return False
        else:
            return True

    def missing_keys(self, fields, skip_defaults=False):
        """
        Determines keys required for use of template which do not exist
        in a given fields.

        Example::

            >>> tk.templates["max_asset_work"].missing_keys({})
            ['Step', 'sg_asset_type', 'Asset', 'version', 'name']

            >>> tk.templates["max_asset_work"].missing_keys({"name": "foo"})
            ['Step', 'sg_asset_type', 'Asset', 'version']


        :param fields: fields to test
        :type fields: mapping (dictionary or other)
        :param skip_defaults: If true, do not treat keys with default values as missing.
        :type skip_defaults: Bool

        :returns: Fields needed by template which are not in inputs keys or which have
                  values of None.
        :rtype: list
        """
        # find shortest keys dictionary
        keys = min(self._keys)
        return self._missing_keys(fields, keys, skip_defaults)

    def _missing_keys(self, fields, keys, skip_defaults):
        """
        Compares two dictionaries to determine keys in second missing in first.

        :param fields: fields to test
        :param keys: Dictionary of template keys to test
        :param skip_defaults: If true, do not treat keys with default values as missing.
        :returns: Fields needed by template which are not in inputs keys or which have
                  values of None.
        """
        missing_key_names = []
        for key in keys.values():
            found_key_name = None
            for key_name in key.names:
                if key_name in fields:
                    found_key_name = key_name
                    break

            if found_key_name:
                # If the found field value is explicitly set to None,
                # call it out as a missing key
                if fields[found_key_name] is None:
                    missing_key_names.append(key.name)
            else:
                # Only add if there isn't a default and skip_defaults isn't True
                if not (key.default and skip_defaults):
                    missing_key_names.append(key.name)

        return missing_key_names

    def apply_fields(self, fields, platform=None):
        """
        Creates path using fields. Certain fields may be processed in special ways, for
        example :class:`SequenceKey` fields, which can take a `FORMAT` string which will intelligently
        format a image sequence specifier based on the type of data is being handled. Example::

            # get a template object from the API
            >>> template_obj = sgtk.templates["maya_shot_publish"]
            <Sgtk Template maya_asset_project: shots/{Shot}/{Step}/pub/{name}.v{version}.ma>

            >>> fields = {'Shot': '001_002',
                          'Step': 'comp',
                          'name': 'main_scene',
                          'version': 3
                          }

            >>> template_obj.apply_fields(fields)
            '/projects/bbb/shots/001_002/comp/pub/main_scene.v003.ma'

        .. note:: For formatting of special values, see :class:`SequenceKey` and :class:`TimestampKey`.

        Example::

            >>> fields = {"Sequence":"seq_1", "Shot":"shot_2", "Step":"comp", "name":"henry", "version":3}

            >>> template_path.apply_fields(fields)
            '/studio_root/sgtk/demo_project_1/sequences/seq_1/shot_2/comp/publish/henry.v003.ma'

            >>> template_path.apply_fields(fields, platform='win32')
            'z:\studio_root\sgtk\demo_project_1\sequences\seq_1\shot_2\comp\publish\henry.v003.ma'

            >>> template_str.apply_fields(fields)
            'Maya Scene henry, v003'


        :param fields: Mapping of keys to fields. Keys must match those in template
                       definition.
        :param platform: Optional operating system platform. If you leave it at the
                         default value of None, paths will be created to match the
                         current operating system. If you pass in a sys.platform-style string
                         (e.g. ``win32``, ``linux2`` or ``darwin``), paths will be generated to
                         match that platform.

        :returns: Full path, matching the template with the given fields inserted.
        """
        return self._apply_fields(fields, platform=platform)

    def _apply_fields(self, fields, ignore_types=None, platform=None):
        """
        Creates path using fields.

        :param fields: Mapping of keys to fields. Keys must match those in template
                       definition.
        :param ignore_types: Keys for whom the defined type is ignored as list of strings.
                            This allows setting a Key whose type is int with a string value.
        :param platform: Optional operating system platform. If you leave it at the
                         default value of None, paths will be created to match the
                         current operating system. If you pass in a sys.platform-style string
                         (e.g. 'win32', 'linux2' or 'darwin'), paths will be generated to
                         match that platform.

        :returns: Full path, matching the template with the given fields inserted.
        """
        ignore_types = ignore_types or []

        # find largest key mapping without missing values
        keys = None
        # index of matching keys will be used to find cleaned_definition
        index = -1
        for index, cur_keys in enumerate(self._keys):
            missing_keys = self._missing_keys(fields, cur_keys, skip_defaults=True)
            if not missing_keys:
                keys = cur_keys
                break

        if keys is None:
            raise TankError("Tried to resolve a path from the template %s and a set "
                            "of input fields '%s' but the following required fields were missing "
                            "from the input: %s" % (self, fields, missing_keys))

        # Process all field values through template keys
        processed_fields = {}
        for key in keys.values():
            for key_name in key.names:
                value = fields.get(key_name)
                if value:
                    break
            ignore_type = key_name in ignore_types
            processed_fields[key.name] = key.str_from_value(value, ignore_type=ignore_type)

        return self._cleaned_definitions[index] % processed_fields

    def _definition_variations(self, definition):
        """
        Determines all possible definition based on combinations of optional sectionals.

        "{foo}"               ==> ['{foo}']
        "{foo}_{bar}"         ==> ['{foo}_{bar}']
        "{foo}[_{bar}]"       ==> ['{foo}', '{foo}_{bar}']
        "{foo}_[{bar}_{baz}]" ==> ['{foo}_', '{foo}_{bar}_{baz}']

        """
        # split definition by optional sections
        tokens = re.split("(\[[^]]*\])", definition)

        # seed with empty string
        definitions = ['']
        found_optional_keys = {}
        for token in tokens:
            temp_definitions = []

            # regex return some blank strings, skip them
            if token == '':
                continue

            # If this is an optional section...
            if token.startswith('['):
                # strip brackets from token
                token = re.sub('[\[\]]', '', token)

                # check that optional contains a key
                key_names = re.findall("{*%s}" % constants.TEMPLATE_KEY_NAME_REGEX, token)
                if not key_names:
                    raise TankError("Optional sections must include a key definition.")

                # Keep track of any found optional keys
                for key_name in key_names:
                    if key_name not in found_optional_keys:
                        found_optional_keys[key_name] = set()
                    found_optional_keys[key_name].add(token)

                # Add definitions skipping this optional value
                temp_definitions = definitions[:]

            # check non-optional contains no dangling brackets
            if re.search("[\[\]]", token):
                raise TankError("Square brackets are not allowed outside of optional section definitions.")

            # make definitions with token appended
            for definition in definitions:
                temp_definitions.append(definition + token)

            definitions = temp_definitions

        # Trim the list of optionally-keyed definitions to the ones with the max number of matches
        # This will ensure an "all or nothing" approach to matching optional parameters
        temp_definitions = set(definitions[:])
        for key_name, tokens in found_optional_keys.iteritems():
            key_definitions = {}
            non_key_definitions = set()
            for definition in temp_definitions:
                token_matches = 0
                for token in tokens:
                    matches = re.findall(token, definition)
                    if matches:
                        token_matches += len(matches)

                # If this is a matching definition, add it to the list sorted by
                # the number of matches
                if token_matches:
                    if token_matches not in key_definitions:
                        key_definitions[token_matches] = set()
                    key_definitions[token_matches].add(definition)
                else:
                    non_key_definitions.add(definition)

            temp_definitions = set(non_key_definitions)
            if key_definitions:
                # If we have matches, add the ones with the most matches to the list
                key_defs = key_definitions[max(key_definitions.keys())]
                temp_definitions.update(key_defs)

        return list(temp_definitions)

    def _fix_key_names(self, definition, keys):
        """
        Substitutes key name for name used in definition
        """
        # Substitute key names for original key input names(key aliasing)
        substitutions = [(key_name, key.name) for key_name, key in keys.items() if key_name != key.name]
        for old_name, new_name in substitutions:
            old_def = r"{%s}" % old_name
            new_def = r"{%s}" % new_name
            definition = re.sub(old_def, new_def, definition)
        return definition

    def _clean_definition(self, definition):
        # Create definition with key names as strings with no format, enum or default values
        regex = r"{(%s)}" % constants.TEMPLATE_KEY_NAME_REGEX
        cleaned_definition = re.sub(regex, "%(\g<1>)s", definition)
        return cleaned_definition

    def _calc_static_tokens(self, definition):
        """
        Finds the tokens from a definition which are not involved in defining keys.
        """
        # expand the definition to include the prefix unless the definition is empty in which
        # case we just want to parse the prefix.  For example, in the case of a path template,
        # having an empty definition would result in expanding to the project/storage root
        expanded_definition = os.path.join(self._prefix, definition) if definition else self._prefix
        regex = r"{%s}" % constants.TEMPLATE_KEY_NAME_REGEX
        tokens = re.split(regex, expanded_definition.lower())
        # Remove empty strings
        return [x for x in tokens if x]

    @property
    def parent(self):
        """
        Returns Template representing the parent of this object.

        :returns: :class:`Template`
        """
        raise NotImplementedError

    def validate_and_get_fields(self, path, required_fields=None, skip_keys=None):
        """
        Takes an input string and determines whether it can be mapped to the template pattern.
        If it can then the list of matching fields is returned. Example::

            >>> good_path = '/studio_root/sgtk/demo_project_1/sequences/seq_1/shot_2/comp/publish/henry.v003.ma'
            >>> template_path.validate_and_get_fields(good_path)
            {'Sequence': 'seq_1',
             'Shot': 'shot_2',
             'Step': 'comp',
             'name': 'henry',
             'version': 3}

            >>> bad_path = '/studio_root/sgtk/demo_project_1/shot_2/comp/publish/henry.v003.ma'
            >>> template_path.validate_and_get_fields(bad_path)
            None


        :param path:            Path to validate
        :param required_fields: An optional dictionary of key names to key values. If supplied these values must
                                be present in the input path and found by the template.
        :param skip_keys:       List of field names whose values should be ignored

        :returns:               Dictionary of fields found from the path or None if path fails to validate
        """
        required_fields = required_fields or {}
        skip_keys = skip_keys or []

        # Path should split into keys as per template
        path_fields = {}
        try:
            path_fields = self.get_fields(path, skip_keys=skip_keys)
        except TankError:
            return None

        # Check that all required fields were found in the path:
        for key_name, value in required_fields.items():
            if key_name in skip_keys:
                continue

            # First try and find a matching key for the field_key_name
            # The result of get_fields will always be keyed by key.name, so ensure
            # we use that for lookup validation regardless of whether or not the user
            # specified the key name or key alias.
            matching_key = None
            for key in self.keys.values():
                for name in key.names:
                    if name == key_name:
                        matching_key = key
                        break

            # If we don't have a matching key, just skip it
            if not matching_key:
                continue

            # Now ensure that the path_fields value matches the required value
            if path_fields.get(matching_key.name) != value:
                return None

        return path_fields

    def validate(self, path, fields=None, skip_keys=None):
        """
        Validates that a path can be mapped to the pattern given by the template. Example::

            >>> good_path = '/studio_root/sgtk/demo_project_1/sequences/seq_1/shot_2/comp/publish/henry.v003.ma'
            >>> template_path.validate(good_path)
            True

            >>> bad_path = '/studio_root/sgtk/demo_project_1/shot_2/comp/publish/henry.v003.ma'
            >>> template_path.validate(bad_path)
            False

        :param path:        Path to validate
        :type path:         String
        :param fields:      An optional dictionary of key names to key values. If supplied these values must
                            be present in the input path and found by the template.
        :type fields:       Dictionary
        :param skip_keys:   Field names whose values should be ignored
        :type skip_keys:    List
        :returns:           True if the path is valid for this template
        :rtype:             Bool
        """
        return self.validate_and_get_fields(path, fields, skip_keys) != None

    def get_fields(self, input_path, skip_keys=None):
        """
        Extracts key name, value pairs from a string. Example::

            >>> input_path = '/studio_root/sgtk/demo_project_1/sequences/seq_1/shot_2/comp/publish/henry.v003.ma'
            >>> template_path.get_fields(input_path)

            {'Sequence': 'seq_1',
             'Shot': 'shot_2',
             'Step': 'comp',
             'name': 'henry',
             'version': 3}

        :param input_path: Source path for values
        :type input_path: String
        :param skip_keys: Optional keys to skip
        :type skip_keys: List

        :returns: Values found in the path based on keys in template
        :rtype: Dictionary
        """
        path_parser = None
        fields = None

        for ordered_keys, static_tokens in zip(self._ordered_keys, self._static_tokens):
            path_parser = TemplatePathParser(ordered_keys, static_tokens)
            fields = path_parser.parse_path(input_path, skip_keys)
            if fields != None:
                break

        if fields is None:
            raise TankError("Template %s: %s" % (str(self), path_parser.last_error))

        return fields

    def get_entities(self, input_path, skip_keys=None):
        """
        Extracts a list of entities from a string that can be used for building a context. Example:

            >>> input_path = '/studio_root/sgtk/demo_project_1/sequences/seq_1/shot_2/comp/dirk.gently'
            >>> template_path.get_entities(input_path)

            [{'type': 'Project',   'id': 10, 'name': 'demo_project_1'},
             {'type': 'Sequence',  'id': 13, 'code': 'seq_1'},
             {'type': 'Shot',      'id': 60, 'code': 'shot_2'},
             {'type': 'Step',      'id': 14, 'code': 'comp'},
             {'type': 'HumanUser', 'id': 23, 'name': 'Dirk Gently'}]

        :param input_path: Source path for values
        :type input_path: String
        :param additional_types: Optional additional types to search for
        :type additional_types: List
        :param skip_keys: Optional keys to skip
        :type skip_keys: List

        :returns: A list of entity dictionaries
        :rtype: List
        """
        entities = []
        sg_filters = []
        entity_searches_by_type = {}

        # Get the shotgun connection object
        sg = shotgun.get_sg_connection()

        # Get fields parsed from the path
        path_fields = self.get_fields(input_path, skip_keys)

        def _add_entity_search(entity_type, field_name, value):
            """
            """
            sg_filter = [field_name, "is", value]
            name_field = shotgun_entity.get_sg_entity_name_field(entity_type)
            fields = ["type", "id", name_field]

            if entity_type not in entity_searches_by_type:
                entity_searches_by_type[entity_type] = (entity_type, [sg_filter], fields)
            else:
                # Else just append the additional filter
                entity_searches_by_type[entity_type][1].append(sg_filter)

        # Preprocess the path fields to generate their corresponding entity searches
        for key_name, value in path_fields.iteritems():
            if key_name not in self.keys:
                log.warning("Cannot find TemplateKey for '%s'. Skipping..." % key_name)
                continue

            template_key = self.keys[key_name]
            if not template_key.shotgun_field_name:
                # This isn't an Shotgun Entity TemplateKey
                continue

            entity_type = template_key.shotgun_entity_type
            field_name = template_key.shotgun_field_name

            # Add a search for this entity key
            _add_entity_search(entity_type, field_name, value)

            # If this is an entity link field...
            if "." in field_name:
                field_split = field_name.split(".")
                sub_entity_type = field_split[-2]
                sub_field_name = field_split[-1]

                # Add a search for the linked entity as well
                _add_entity_search(sub_entity_type, sub_field_name, value)


        # Treat HumanUser entity special since it can be parsed without a Project entity
        if "HumanUser" in entity_searches_by_type:
            entity_search = entity_searches_by_type.pop("HumanUser")

            user_entity = sg.find_one(*entity_search)
            if user_entity is None:
                raise TankError("Cannot find '%s' Entity matching search: %s %s" % entity_search)

            # Add to list of entities
            entities.append(user_entity)


        # First see if we can get the Project entity from the PipelineConfiguration
        proj_id = self.pipeline_configuration.get_project_id()
        if proj_id is not None:
            name_field = shotgun_entity.get_sg_entity_name_field("Project")
            proj_entity = {
                "type": "Project",
                "id": proj_id,
                name_field: self.pipeline_configuration.get_project_disk_name()
            }

        # Else see if we can process a provided Project entity search
        elif "Project" in entity_searches_by_type:
            entity_search = entity_searches_by_type.pop("Project")

            proj_entity = sg.find_one(*entity_search)
            if proj_entity is None:
                raise TankError("Cannot find '%s' Entity matching search: %s %s" % entity_search)

        # If we have a Project, entity...
        if proj_entity:
            # Append it to the entities list
            entities.append(proj_entity)

            # Filter all further entity searches by it
            sg_filters.append(["project", "is", proj_entity])

            # And make sure we exclude Project from any future searches
            if "Project" in entity_searches_by_type:
                entity_searches_by_type.pop("Project")

        # Else we can't resolve anything else if we're outside a project
        else:
            # ...so just return
            return entities


        # Next process any primary entity types (in hierarchy order)
        entity_filter = None
        for entity_type in ("Sequence", "Shot", "Asset"):

            # Skip if its not in the list of entities to process
            if entity_type not in entity_searches_by_type:
                continue

            entity_search = entity_searches_by_type.pop(entity_type)

            # Append the project entity filter
            entity_search[1].extend(sg_filters)

            # Append any previous primary entity filter
            if entity_filter:
                entity_search[1].append(entity_filter)

            entity = sg.find_one(*entity_search)
            if entity is None:
                raise TankError("Cannot find '%s' Entity matching search: %s %s" % entity_search)

            # Append the entity
            entities.append(entity)

            # Update the entity_filter for the next level
            entity_filter = ["sg_%s" % entity_type.lower(), "is", entity]


        # If we have an entity_filter, then we've processed a primary entity
        if entity_filter:
            # Filter all further entity searches by it
            sg_filters.append(entity_filter)

            # Treat Step entity special since it requires a primary entity
            if "Step" in entity_searches_by_type:
                step_entity_type, step_sg_filters, step_sg_fields = entity_searches_by_type.pop("Step")

                # Filter step entity by the parent entity type
                step_filters = [["entity_type", "is", entities[-1]["type"]]]
                step_sg_filters.extend(step_filters)

                step_entity = sg.find_one(step_entity_type, step_sg_filters, step_sg_fields)
                if step_entity is None:
                    raise TankError("Cannot find '%s' Entity matching search: %s %s" %
                                    (step_entity_type, step_sg_filters, step_sg_fields))

                # Add to list of entities
                entities.append(step_entity)


        # Now process the remaining fields
        for entity_type, entity_search in entity_searches_by_type.iteritems():

            # Allow the user to override the entity search to run
            entity_search = self.pipeline_configuration.execute_core_hook_internal(
                                            "template_additional_entities",
                                            self,
                                            entity_type=entity_type,
                                            entity_search=entity_search,
                                            sg_filters=sg_filters)

            # Skip if no entity_search is provided
            if not entity_search:
                continue

            entity = sg.find_one(*entity_search)
            if entity is None:
                raise TankError("Cannot find '%s' Entity matching search: %s %s" % entity_search)

            # Add to list of entities
            entities.append(entity)

        return entities

    def get_entity_fields(self, entities, validate=False):
        """
        Returns a dictionary of field keys and their matching values corresponding to the entities
        that match the fields of the Template object.

        :param entities:    A list of entity dictionaries
        :type entities:     List
        :param validate:    If True then the fields found will be checked to ensure that all
                            expected fields for the entity was found.  If a field is missing then
                            a :class:`TankError` will be raised
        :type validate:     Bool

        :returns: A dictionary of template fields found matching the input entities.
        :rtype: Dictionary
        """
        fields = {}
        entity_dict = dict([(x["type"], x) for x in entities])

        for key in self.keys.values():

            # check each key to see if it has shotgun query information that we should resolve
            if key.shotgun_field_name:
                # this key is a shotgun value that needs fetching!

                # ensure that the input list actually provides the desired entities
                if not key.shotgun_entity_type in entity_dict:
                    continue

                entity = entity_dict[key.shotgun_entity_type]
                entity_type = entity["type"]

                # See if we already have the value
                if key.shotgun_field_name in entity:
                    fields[key.name] = entity[key.shotgun_field_name]

                else:

                    # check the entity cache
                    cache_key = (entity["type"], entity["id"], key.shotgun_field_name)
                    if cache_key in self._entity_fields_cache:
                        # already have the value cached - no need to fetch from shotgun
                        fields[key.name] = self._entity_fields_cache[cache_key]

                    else:
                        # get the value from shotgun
                        filters = [["id", "is", entity["id"]]]
                        query_fields = [key.shotgun_field_name]

                        # Get the shotgun connection object
                        sg = shotgun.get_sg_connection()

                        result = sg.find_one(key.shotgun_entity_type, filters, query_fields)
                        if not result:
                            # no record with that id in shotgun!
                            raise TankError("Could not retrieve Shotgun data for key '%s'. "
                                            "No records in Shotgun are matching "
                                            "entity '%s' (Which is part of the current "
                                            "Template '%s')" % (key, entity, self))

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
                            processed_val = self.pipeline_configuration.execute_core_hook_internal(
                                                            "process_folder_name",
                                                            self,
                                                            entity_type=key.shotgun_entity_type,
                                                            entity_id=entity.get("id"),
                                                            field_name=key.shotgun_field_name,
                                                            value=value)

                            if validate and not key.validate(processed_val):
                                raise TankError("Template validation failed for value '%s'. This "
                                                "value was retrieved from entity %s in Shotgun to "
                                                "represent key '%s'." % (processed_val, entity, key))

                        # all good!
                        # populate dictionary and cache
                        fields[key.name] = processed_val
                        self._entity_fields_cache[cache_key] = processed_val

        return fields


class TemplatePath(Template):
    """
    :class:`Template` representing a complete path on disk. The template definition is multi-platform
    and you can pass it per-os roots given by a separate :meth:`root_path`.
    """
    def __init__(self, definition, keys, pipeline_configuration, root_path, name=None, per_platform_roots=None):
        """
        TemplatePath objects are typically created automatically by toolkit reading
        the template configuration.

        :param definition: Template definition string.
        :param keys: Mapping of key names to keys (dict)
        :param pipeline_configuration: The associated PipelineConfiguration object this belongs to.
        :param root_path: Path to project root for this template.
        :param name: Optional name for this template.
        :param per_platform_roots: Root paths for all supported operating systems.
                                   This is a dictionary with sys.platform-style keys
        """
        super(TemplatePath, self).__init__(definition, keys, pipeline_configuration, name=name)
        self._prefix = root_path
        self._per_platform_roots = per_platform_roots
        self._token = os.path.sep

        # Make definition use platform separator
        for index, rel_definition in enumerate(self._definitions):
            self._definitions[index] = os.path.join(*split_path(rel_definition))

        # get definition ready for string substitution
        self._cleaned_definitions = []
        for definition in self._definitions:
            self._cleaned_definitions.append(self._clean_definition(definition))

        # split by format strings the definition string into tokens
        self._static_tokens = []
        for definition in self._definitions:
            self._static_tokens.append(self._calc_static_tokens(definition))

    @property
    def root_path(self):
        """
        Returns the root path associated with this template.
        """
        return self._prefix

    @property
    def parent(self):
        """
        Returns Template representing the parent of this object.

        For paths, this means the parent folder.

        :returns: :class:`Template`
        """
        parent_definition = os.path.dirname(self.definition)
        if parent_definition:
            return TemplatePath(parent_definition,
                                self.keys,
                                self.pipeline_configuration,
                                self.root_path,
                                None,
                                self._per_platform_roots)
        return None

    def _apply_fields(self, fields, ignore_types=None, platform=None):
        """
        Creates path using fields.

        :param fields: Mapping of keys to fields. Keys must match those in template
                       definition.
        :param ignore_types: Keys for whom the defined type is ignored as list of strings.
                            This allows setting a Key whose type is int with a string value.
        :param platform: Optional operating system platform. If you leave it at the
                         default value of None, paths will be created to match the
                         current operating system. If you pass in a sys.platform-style string
                         (e.g. 'win32', 'linux2' or 'darwin'), paths will be generated to
                         match that platform.

        :returns: Full path, matching the template with the given fields inserted.
        """
        relative_path = super(TemplatePath, self)._apply_fields(fields, ignore_types, platform)

        if platform is None:
            # return the current OS platform's path
            return os.path.join(self.root_path, relative_path) if relative_path else self.root_path

        else:
            # caller has requested a path for another OS
            if self._per_platform_roots is None:
                # it's possible that the additional os paths are not set for a template
                # object (mainly because of backwards compatibility reasons) and in this case
                # we cannot compute the path.
                raise TankError("Template %s cannot resolve path for operating system '%s' - "
                                "it was instantiated in a mode which only supports the resolving "
                                "of current operating system paths." % (self, platform))

            platform_root_path = self._per_platform_roots.get(platform)

            if platform_root_path is None:
                # either the platform is undefined or unknown
                raise TankError("Cannot resolve path for operating system '%s'! Please ensure "
                                "that you have a valid storage set up for this platform." % platform)

            elif platform == "win32":
                # use backslashes for windows
                if relative_path:
                    return "%s\\%s" % (platform_root_path, relative_path.replace(os.sep, "\\"))
                else:
                    # not path generated - just return the root path
                    return platform_root_path

            elif platform == "darwin" or "linux" in platform:
                # unix-like plaforms - use slashes
                if relative_path:
                    return "%s/%s" % (platform_root_path, relative_path.replace(os.sep, "/"))
                else:
                    # not path generated - just return the root path
                    return platform_root_path

            else:
                raise TankError("Cannot evaluate path. Unsupported platform '%s'." % platform)


class TemplateString(Template):
    """
    :class:`Template` class for templates representing strings.

    Templated strings are useful if you want to write code where you can configure
    the formatting of strings, for example how a name or other string field should
    be configured in Shotgun, given a series of key values.
    """
    def __init__(self, definition, keys, pipeline_configuration, name=None, validate_with=None):
        """
        TemplatePath objects are typically created automatically by toolkit reading
        the template configuration.

        :param definition: Template definition string.
        :param keys: Mapping of key names to keys (dict)
        :param pipeline_configuration: The associated PipelineConfiguration object this belongs to.
        :param name: Optional name for this template.
        :param validate_with: Optional :class:`Template` to use for validation
        """
        super(TemplateString, self).__init__(definition, keys, pipeline_configuration, name=name)
        self.validate_with = validate_with
        self._prefix = "@"
        self._token = "_"

        # split by format strings the definition string into tokens
        self._static_tokens = []
        for definition in self._definitions:
            self._static_tokens.append(self._calc_static_tokens(definition))

    @property
    def parent(self):
        """
        Strings don't have a concept of parent so this always returns ``None``.
        """
        return None

    def get_fields(self, input_path, skip_keys=None):
        """
        Extracts key name, value pairs from a string. Example::

            >>> input = 'filename.v003.ma'
            >>> template_string.get_fields(input)

            {'name': 'henry',
             'version': 3}

        :param input_path: Source path for values
        :type input_path: String
        :param skip_keys: Optional keys to skip
        :type skip_keys: List

        :returns: Values found in the path based on keys in template
        :rtype: Dictionary
        """
        # add path prefix as original design was to require project root
        adj_path = os.path.join(self._prefix, input_path)
        return super(TemplateString, self).get_fields(adj_path, skip_keys=skip_keys)

def split_path(input_path):
    """
    Split a path into tokens.

    :param input_path: path to split
    :type input_path: string

    :returns: tokenized path
    :rtype: list of tokens
    """
    cur_path = os.path.normpath(input_path)
    cur_path = cur_path.replace("\\", "/")
    return cur_path.split("/")

def read_templates(pipeline_configuration, engine_name):
    """
    Creates templates and keys based on contents of templates file.

    :param pipeline_configuration: pipeline config object
    :param engine_name: the engine instance name to lookup templates for

    :returns: Dictionary of form {template name: template object}
    """
    per_platform_roots = pipeline_configuration.get_all_platform_data_roots()
    data = pipeline_configuration.get_templates_config(engine_name)

    # get dictionaries from the templates config file:
    def get_data_section(section_name):
        # support both the case where the section
        # name exists and is set to None and the case where it doesn't exist
        d = data.get(section_name)
        if d is None:
            d = {}
        return d

    keys = templatekey.make_keys(pipeline_configuration, get_data_section("keys"))
    template_paths = make_template_paths(pipeline_configuration, get_data_section("paths"), keys, per_platform_roots, default_root=pipeline_configuration.get_primary_data_root_name())
    template_strings = make_template_strings(pipeline_configuration, get_data_section("strings"), keys, template_paths)
    template_aliases = make_template_aliases(pipeline_configuration, get_data_section("aliases"), template_strings, template_paths)

    # Detect duplicate names across paths and strings
    dup_names = set(template_paths).intersection(set(template_strings).intersection(set(template_aliases)))
    if dup_names:
        raise TankError("Detected templates with the same name: %s" % str(list(dup_names)))

    # Put path and strings together
    templates = template_paths
    templates.update(template_strings)
    templates.update(template_aliases)
    return templates, keys


def make_template_paths(pipeline_configuration, data, keys, all_per_platform_roots, default_root=None):
    """
    Factory function which creates TemplatePaths.

    :param pipeline_configuration: The associated PipelineConfiguration object this item belongs to.
    :param data: Data from which to construct the template paths.
                 Dictionary of form: {<template name>: {<option>: <option value>}}
    :param keys: Available keys. Dictionary of form: {<key name> : <TemplateKey object>}
    :param all_per_platform_roots: Root paths for all platforms. nested dictionary first keyed by
                                   storage root name and then by sys.platform-style os name.

    :returns: Dictionary of form {<template name> : <TemplatePath object>}
    """

    if data and not all_per_platform_roots:
        raise TankError(
            "At least one root must be defined when using 'path' templates."
        )

    template_paths = {}
    templates_data = _process_templates_data(data, "path")

    for template_name, template_data in templates_data.items():
        definition = template_data["definition"]
        root_name = template_data.get("root_name")
        if not root_name:
            # If the root name is not explicitly set we use the default arg
            # provided
            if default_root:
                root_name = default_root
            else:
                raise TankError(
                    "The template %s (%s) can not be evaluated. No root_name "
                    "is specified, and no root name can be determined from "
                    "the configuration. Update the template definition to "
                    "include a root_name or update your configuration's "
                    "roots.yml file to mark one of the storage roots as the "
                    "default: `default: true`." % (template_name, definition)
                )
        # to avoid confusion between strings and paths, validate to check
        # that each item contains at least a "/" (#19098)
        if "/" not in definition:
            raise TankError("The template %s (%s) does not seem to be a valid path. A valid "
                            "path needs to contain at least one '/' character. Perhaps this "
                            "template should be in the strings section "
                            "instead?" % (template_name, definition))

        root_path = all_per_platform_roots.get(root_name, {}).get(sys.platform)
        if root_path is None:
            raise TankError("Undefined Shotgun storage! The local file storage '%s' is not defined for this "
                            "operating system." % root_name)

        template_path = TemplatePath(
            definition,
            keys,
            pipeline_configuration,
            root_path,
            template_name,
            all_per_platform_roots[root_name]
        )
        template_paths[template_name] = template_path

    return template_paths

def make_template_strings(pipeline_configuration, data, keys, template_paths):
    """
    Factory function which creates TemplateStrings.

    :param pipeline_configuration: The associated PipelineConfiguration object this item belongs to.
    :param data: Data from which to construct the template strings.
    :type data:  Dictionary of form: {<template name>: {<option>: <option value>}}
    :param keys: Available keys.
    :type keys:  Dictionary of form: {<key name> : <TemplateKey object>}
    :param template_paths: TemplatePaths available for optional validation.
    :type template_paths: Dictionary of form: {<template name>: <TemplatePath object>}

    :returns: Dictionary of form {<template name> : <TemplateString object>}
    """
    template_strings = {}
    templates_data = _process_templates_data(data, "string")

    for template_name, template_data in templates_data.items():
        definition = template_data["definition"]

        validator_name = template_data.get("validate_with")
        validator = template_paths.get(validator_name)
        if validator_name and not validator:
            msg = "Template %s validate_with is set to undefined template %s."
            raise TankError(msg %(template_name, validator_name))

        template_string = TemplateString(definition,
                                         keys,
                                         pipeline_configuration,
                                         template_name,
                                         validate_with=validator)

        template_strings[template_name] = template_string

    return template_strings

def make_template_aliases(pipeline_configuration, data, template_strings, template_paths):
    """
    Factory function which creates aliases for TemplatePaths or TemplateStrings.

    :param pipeline_configuration: The associated PipelineConfiguration object this item belongs to.
    :param data: Data from which to construct the template aliases.
    :type data:  Dictionary of form: {<template name>: {<option>: <option value>}}
    :param template_string: TemplateStrings available for optional validation.
    :type template_string: Dictionary of form: {<template name>: <TemplateString object>}
    :param template_paths: TemplatePaths available for optional validation.
    :type template_paths: Dictionary of form: {<template name>: <TemplatePath object>}

    :returns: Dictionary of form {<template name> : <TemplateString|TemplatePath object>}
    """
    template_aliases = {}
    templates_data = _process_templates_data(data, "alias")

    for template_name, template_data in templates_data.items():
        definition = template_data["definition"]

        if definition in template_paths:
            template_aliases[template_name] = template_paths[definition]
        elif definition in template_strings:
            template_aliases[template_name] = template_strings[definition]
        else:
            raise TankError("Template alias '%s' refers to non-existent Template '%s'" %
                    (template_name, definition))

    return template_aliases

def _conform_template_data(template_data, template_name):
    """
    Takes data for single template and conforms it expected data structure.
    """
    if isinstance(template_data, basestring):
        template_data = {"definition": template_data}
    elif not isinstance(template_data, dict):
        raise TankError("template %s has data which is not a string or dictionary." % template_name)

    if "definition" not in template_data:
        raise TankError("Template %s missing definition." % template_name)

    return template_data

def _process_templates_data(data, template_type):
    """
    Conforms templates data and checks for duplicate definitions.

    :param data: Dictionary in form { <template name> : <data> }
    :param template_type: path, string, or alias

    :returns: Processed data.
    """
    templates_data = {}

    # Track path definitions to detect duplicates
    definitions = {}

    for template_name, template_data in data.items():
        cur_data = _conform_template_data(template_data, template_name)
        definition = cur_data["definition"]
        if template_type == "path":
            if "root_name" not in cur_data:
                cur_data["root_name"] = constants.PRIMARY_STORAGE_NAME

            # Record this templates definition
            cur_key = (cur_data["root_name"], definition)
            definitions[cur_key] = definitions.get(cur_key, []) + [template_name]

        templates_data[template_name] = cur_data


    dups_msg = ""
    for (root_name, definition), template_names in definitions.items():
        if len(template_names) > 1:
            # We have a duplicate
            dups_msg += "%s: %s\n" % (", ".join(template_names), definition)

    if dups_msg:
        raise TankError("It looks like you have one or more "
                        "duplicate entries in your templates.yml file. Each template path that you "
                        "define in the templates.yml file needs to be unique, otherwise toolkit "
                        "will not be able to resolve which template a particular path on disk "
                        "corresponds to. The following duplicate "
                        "templates were detected:\n %s" % dups_msg)

    return templates_data
