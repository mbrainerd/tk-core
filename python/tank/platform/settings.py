import os
import copy
import collections

from . import constants
from . import validation
from .errors import TankCurrentModuleNotFoundError
from ..log import LogManager

core_logger = LogManager.get_logger(__name__)

def create_settings(settings, schema, bundle=None, validate=False):
    """
    """
    settings_objs = {}

    # Allow for non-schema'd setting values
    setting_keys = set(settings.keys() + schema.keys())
    for setting_key in setting_keys:
        setting_value = settings.get(setting_key)
        setting_schema = schema.get(setting_key)
        setting = create_setting(
            setting_key,
            setting_value,
            setting_schema,
            bundle
        )
        if validate:
            setting.validate()

        settings_objs[setting_key] = setting

    return settings_objs

def create_setting(name, value, schema, bundle=None, tk=None, engine_name=None):
    """
    """
    schema = schema or {}
    setting_type = schema.get("type")
    if isinstance(value, list) or setting_type == "list":
        return ListSetting(name, value, schema, bundle, tk, engine_name)
    elif isinstance(value, dict) or setting_type == "dict":
        return DictSetting(name, value, schema, bundle, tk, engine_name)
    else:
        return Setting(name, value, schema, bundle, tk, engine_name)

class Setting(object):
    """
    This class provides an interface to settings defined for a given bundle.
    """

    def __init__(self, name, value, schema, bundle=None, tk=None, engine_name=None):
        """
        TA few special keys
        are set by default and are accessible after initialization. Those keys
        are:

        * ``default_value``: The default value as configured for this setting.
        * ``description``: Any description provided for this setting in the config.
        * ``name``: The display name for this setting.
        * ``schema``: The schema configured for this setting.
        * ``type``: The type for this setting (:py:attr:`bool`, :py:attr:`str`, etc).
        * ``value``: The current value of this setting.
        """
        # Get the current bundle if one is not provided
        if bundle is None:
            try:
                from .util import current_bundle
                bundle = current_bundle()
            except TankCurrentModuleNotFoundError:
                pass

        # Get the tk instance. This must be defined, so if its not passed explicitly
        # or derived from a bundle object, we should fail
        if tk is None:
            try:
                tk = bundle.sgtk
            except AttributeError:
                pass

        # Get the engine name. This must be defined, so if its not passed explicitly
        # or derived from a bundle object, we should fail
        if engine_name is None:
            try:
                engine_name = bundle._get_engine_name()
            except AttributeError:
                pass

        self._bundle = bundle
        self._engine_name = engine_name
        self._name = name
        self._schema = schema or {}
        self._tk = tk
        self._type = self._schema.get("type")
        self._description = self._schema.get("description")

        self._cache = dict()

        self._default_value = self._process_default_value()
        self._value, self._children = self._process_value(value, self._default_value)

    def __repr__(self):
        return "<%s %s: %s>" % (self.__class__.__name__, self._name, self.value)

    def __str__(self):
        return str(self.value)

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.value == other.value
        return self.value == other

    def __ne__(self, other):
        return not (self == other)

    def __contains__(self, key):
        return key in self.value

    def __deepcopy__(self, memo):
        """
        Allow setting to be deepcopied - Note that the class
        members are _never_ copied
        """
        return self.__class__(**self.to_dict())

    def to_dict(self):
        """
        Converts the setting into a dictionary that can be used to instantiate a
        new :class:`Setting` object.

        :returns: A dictionary representing the setting.
        """
        return {
            "name": self._name,
            "value": copy.deepcopy(self._value),
            "schema": copy.deepcopy(self._schema),
            "bundle": self._bundle,
            "tk": self._tk,
            "engine_name": self._engine_name
        }

    @classmethod
    def from_dict(cls, data):
        """
        Creates a Setting object based on the arguments found in a dictionary.

        :param dict data: Data for the setting.

        :returns: :class:`Setting`
        """
        return create_setting(
            name=data.get("name"),
            value=data.get("value"),
            schema=data.get("schema"),
            bundle=data.get("bundle"),
            tk=data.get("tk"),
            engine_name=data.get("engine_name")
        )

    def _process_value(self, value, default=None):
        """
        """
        processed_val = None
        children = None

        # Use default if value is None or user defined "default"
        if value is None or value == constants.TANK_BUNDLE_DEFAULT_HOOK_SETTING:
            value = default

        # If value is None
        if value is None:
            # Assign "empty" values if allows_empty is True
            if self._schema.get("allows_empty", False):
                if self._type == "list":
                    processed_val = []
                    children = []
                elif self._type == "dict":
                    processed_val = {}
                    children = {}

            # No further processing necessary
            return processed_val, children

        if isinstance(value, basestring) and value.startswith("hook:"):
            # handle the special form where the value is computed in a hook.
            #
            # if the template parameter is on the form
            # a) hook:foo_bar
            # b) hook:foo_bar:testing:testing
            #
            # The following hook will be called
            # a) foo_bar with parameters []
            # b) foo_bar with parameters [testing, testing]
            #
            chunks = value.split(":")
            hook_name = chunks[1]
            params = chunks[2:]
            value = self._tk.execute_core_hook(
                hook_name,
                setting=self._name,
                settings_type=self._type,
                bundle_obj=self._bundle,
                extra_params=params
            )

        if isinstance(value, list):
            processed_val = []
            children = []
    
            value_schema = self._schema.get("values")
            for i, sub_value in enumerate(value):
                value_name = "%s[%s]" % (self._name, str(i))
                setting = create_setting(
                    value_name,
                    sub_value,
                    value_schema,
                    self._bundle,
                    self._tk,
                    self._engine_name
                )

                processed_val.append(setting.raw_value)
                children.append(setting)

        elif isinstance(value, dict):
            processed_val = {}
            children = {}

            # If there is an item list, then we are dealing with a strict definition
            items = self._schema.get("items")
            if items:
                for sub_key, value_schema in items.iteritems():
                    value_name = "%s[\"%s\"]" % (self._name, sub_key)
                    sub_value = value.get(sub_key)
                    setting = create_setting(
                        value_name,
                        sub_value,
                        value_schema,
                        self._bundle,
                        self._tk,
                        self._engine_name
                    )

                    processed_val[sub_key] = setting.raw_value
                    children[sub_key] = setting

            # Else just process the user-defined items
            else:
                value_schema = self._schema.get("values")
                for sub_key, sub_value in value.iteritems():
                    value_name = "%s.%s" % (self._name, sub_key)
                    setting = create_setting(
                        value_name,
                        sub_value,
                        value_schema,
                        self._bundle,
                        self._tk,
                        self._engine_name
                    )

                    processed_val[sub_key] = setting.raw_value
                    children[sub_key] = setting

        elif isinstance(value, basestring):
            processed_val = value
            if self._type == "config_path":
                # Expand any "config_path" values
                processed_val = expand_config_path(self._tk, processed_val, self._bundle)

            elif self._type == "hook" and not processed_val.startswith("{"):
                # This is an old-style hook. In order to maintain backwards
                # compatibility, return the value in the new style.
                processed_val = "{self}/%s.py" % (processed_val,)

        else:
            #pass-through
            processed_val = value

        return processed_val, children

    def _process_default_value(self, value=None):
        """
        """
        # Engine-specific default value keys are allowed (ex: "default_value_tk-maya").
        # Build the corresponding engine-specific default value key.
        engine_default_key = "%s_%s" % (
            constants.TANK_SCHEMA_DEFAULT_VALUE_KEY,
            self._engine_name
        )

        # Now look for a default value to use.
        if engine_default_key in self._schema:
            # An engine specific key exists, use it.
            value = self._schema[engine_default_key]
        elif constants.TANK_SCHEMA_DEFAULT_VALUE_KEY in self._schema:
            # The standard default value key
            value = self._schema[constants.TANK_SCHEMA_DEFAULT_VALUE_KEY]

        if value:
            # Special processing for default values
            if self._type == "hook":
                # Replace the engine reference token if it exists and there is an engine.
                # In some instances, such as during engine startup, as apps are being
                # validated, the engine instance name may not be available. This might be ok
                # since hooks are actually evaluated just before they are executed. We'll
                # simply return the value with the engine name token intact.
                if constants.TANK_HOOK_ENGINE_REFERENCE_TOKEN in value:
                    value = value.replace(
                        constants.TANK_HOOK_ENGINE_REFERENCE_TOKEN,
                        self._engine_name
                    )

        return value

    def __resolve_value(self, value):
        """
        Gets run "on the fly" since parameters are dynamic
        """
        if isinstance(value, basestring):
            # Expand any internal variables (i.e. engine_name, env_name)
            if (constants.TANK_HOOK_ENGINE_REFERENCE_TOKEN in value or
                constants.TANK_HOOK_ENV_REFERENCE_TOKEN in value):
                processed_val = self._bundle.resolve_setting_expression(value)
            else:
                processed_val = value

            # Expand any environment variables
            processed_val = os.path.expandvars(os.path.expanduser(processed_val))

        elif isinstance(value, list):
            processed_val = []
            for sub_value in value:
                processed_val.append(self.__resolve_value(sub_value))

        elif isinstance(value, dict):
            processed_val = {}
            for sub_key, sub_value in value.iteritems():
                processed_val[sub_key] = self.__resolve_value(sub_value)
        else:
            #pass-through
            processed_val = value

        return processed_val

    @property
    def bundle(self):
        """
        The :class:`TankBundle` object for the setting.
        """
        return self._bundle

    @property
    def default_value(self):
        """
        The default value of the setting.
        """
        return self.__resolve_value(self._default_value)

    @property
    def description(self):
        """
        The description of the setting
        """
        return self._description

    @property
    def engine_name(self):
        """
        The engine_name of the setting
        """
        return self._engine_name

    @property
    def name(self):
        """
        The setting name
        """
        return self._name

    @property
    def raw_value(self):
        """
        The unresolved value of the setting
        """
        return self._value

    @property
    def schema(self):
        """
        The configured schema for the setting
        """
        return self._schema

    @property
    def tk(self):
        """
        The :class:`Sgtk` object for this setting
        """
        return self._tk

    @property
    def type(self):
        """
        The data type of the setting.
        """
        return self._type

    @property
    def cache(self):
        """
        Cache to store random things.
        """
        return self._cache

    @property
    def value(self):
        """
        The current value of the setting
        """
        return self.__resolve_value(self._value)

    @value.setter
    def value(self, value):
        """
        Set the raw value of the setting
        """
        self._value, self._children = self._process_value(value, self._default_value)

    def validate(self):
        """
        Validate the setting
        """
        validation.validate_setting(
            self._bundle.instance_name,
            self._bundle.sgtk,
            self._bundle.context,
            self._schema,
            self._name,
            self.value,
            True
        )

class ListSetting(Setting, collections.Sequence):
    """
    """
    def __getitem__(self, key):
        return self._children[key]

    def __len__(self):
        return len(self._children)


class DictSetting(Setting, collections.Mapping):
    """
    """
    def __getitem__(self, key):
        return self._children[key]

    def __iter__(self):
        return iter(self._children)

    def __len__(self):
        return len(self._children)

def resolve_setting_expression(value, engine_name, env_name):
    """
    Resolves any embedded references like {engine_name} or {env_name}.

    :param value: The value that should be resolved.
    :param engine_name: The engine instance name that should be used to resolve the value.
    :param env_name: The environment name that should be used to resolve the value.

    :returns: An expanded value.
    """
    # make sure to replace the `{engine_name}` token if it exists.
    if constants.TANK_HOOK_ENGINE_REFERENCE_TOKEN in value:
        if not engine_name:
            raise TankError(
                "No engine could be determined for value '%s'. "
                "The setting could not be resolved." % (value,))
        else:
            value = value.replace(
                constants.TANK_HOOK_ENGINE_REFERENCE_TOKEN,
                engine_name,
            )

    # make sure to replace the `{env_name}` token if it exists.
    if constants.TANK_HOOK_ENV_REFERENCE_TOKEN in value:
        if not env_name:
            raise TankError(
                "No environment could be determined for value '%s'. "
                "The setting could not be resolved." % (value,))
        else:
            value = value.replace(
                constants.TANK_HOOK_ENV_REFERENCE_TOKEN,
                env_name,
            )

    return value


def expand_config_path(tk, path, bundle=None):
    """
    Resolves a "config_path" type setting into an absolute path.

    :param tk: :class:`~sgtk.Sgtk` Toolkit API instance
    :param path: The path value that should be resolved.
    :param bundle: The bundle object. This is only used in situations where
        a path's value must be resolved via a bundle. If None, the
        current bundle, as provided by sgtk.platform.current_bundle, will
        be used.
    :returns: An expanded absolute path to the specified file.
    """
    try:
        from .util import current_bundle
        bundle = bundle or current_bundle()
    except TankCurrentModuleNotFoundError:
        pass

    # make sure to replace `{engine_name}`/`{env_name}` tokens if they exist.
    if (constants.TANK_HOOK_ENGINE_REFERENCE_TOKEN in path or
        constants.TANK_HOOK_ENV_REFERENCE_TOKEN in path):
        path = bundle.resolve_setting_expression(path)

    if path.startswith("{self}"):
        # bundle local reference
        parent_folder = bundle.disk_location
        path = path.replace("{self}", parent_folder)
        path = path.replace("/", os.path.sep)

    elif path.startswith("{config}"):
        # config dir reference
        parent_folder = tk.pipeline_configuration.get_config_location()
        path = path.replace("{config}", parent_folder)
        path = path.replace("/", os.path.sep)

    elif path.startswith("{engine}"):
        # look for the hook in the currently running engine
        try:
            engine = bundle._get_engine()
        except AttributeError:
            raise TankError(
                "%s: Could not determine the current "
                "engine. Unable to resolve path for: '%s'" %
                (bundle, path)
            )
        parent_folder = engine.disk_location
        path = path.replace("{engine}", parent_folder)
        path = path.replace("/", os.path.sep)

    elif path.startswith("{$") and "}" in path:
        # environment variable: {$HOOK_PATH}/path/to/foo.py
        env_var = re.match("^\{\$([^\}]+)\}", path).group(1)
        if env_var not in os.environ:
            raise TankError("%s: This path is referring to the configuration value '%s', "
                            "but no environment variable named '%s' can be "
                            "found!" % (bundle, path, env_var))
        env_var_value = os.environ[env_var]
        path = path.replace("{$%s}" % env_var, env_var_value)
        path = path.replace("/", os.path.sep)        

    elif path.startswith("{") and "}" in path:
        # bundle instance (e.g. '{tk-framework-perforce_v1.x.x}/foo/bar.py' )
        # first find the bundle instance
        instance = re.match("^\{([^\}]+)\}", path).group(1)
        # for now, only look at framework instance names. Later on,
        # if the request ever comes up, we could consider extending
        # to supporting app instances etc. However we would need to
        # have some implicit rules for handling ambiguity since
        # there can be multiple items (engines, apps etc) potentially
        # having the same instance name.
        fw_instances = bundle.env.get_frameworks()
        if instance not in fw_instances:
            raise TankError("%s: This path is referring to the configuration value '%s', "
                            "but no framework with instance name '%s' can be found in the currently "
                            "running environment. The currently loaded frameworks "
                            "are %s." % (bundle, path, instance, ", ".join(fw_instances)))

        fw_desc = bundle.env.get_framework_descriptor(instance)
        if not(fw_desc.exists_local()):
            raise TankError("%s: This path is referring to the configuration value '%s', "
                            "but the framework with instance name '%s' does not exist on disk. Please run "
                            "the tank cache_apps command." % (bundle, path, instance))

        # get path to framework on disk
        parent_folder = fw_desc.get_path()
        # create the path to the file
        path = path.replace("{%s}" % instance, parent_folder)
        path = path.replace("/", os.path.sep)

    else:
        # this is a config path. Stored on the form
        # foo/bar/baz.png, we should translate that into
        # PROJECT_PATH/tank/config/foo/bar/baz.png
        parent_folder = tk.pipeline_configuration.get_config_location()
        path = os.path.join(parent_folder, path)
        path = path.replace("/", os.path.sep)

    return path
