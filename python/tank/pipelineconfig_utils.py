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
Encapsulates the pipeline configuration and helps navigate and resolve paths
across storages, configurations etc.
"""

from __future__ import with_statement

import os

from dd.runtime import api
api.load('prez')
import prez

from tank_vendor import yaml

from . import constants
from . import LogManager

from .util import yaml_cache
from .util import StorageRoots
from .util import ShotgunPath
from .util.singleton import Threaded
from .util.shotgun import get_deferred_sg_connection, get_sg_connection

from .errors import TankError

logger = LogManager.get_logger(__name__)

class PackageCache(Threaded):
    """
    Cache of plugin settings per context.
    """
    def __init__(self):
        """
        Constructor.
        """
        Threaded.__init__(self)
        self._cache = dict()

    @Threaded.exclusive
    def get(self, key):
        """
        Retrieve the cached context.

        :param key: The key for the package we desire.

        :returns: The associated package location or None
        """
        return self._cache.get(key)

    @Threaded.exclusive
    def add(self, key, package):
        """
        Cache the location for a given package lookup dict.

        :param key: The key to associate with the package.
        :param package: Package location to be cached.
        """
        self._cache[key] = package

g_package_cache = PackageCache()


def has_core_descriptor(pipeline_config_path):
    """
    Returns ``True`` if the pipeline configuration contains a core descriptor
    file.

    :param pipeline_config_path: path to a pipeline configuration root folder
    :return: ``True`` if the core descriptor file exists, ``False`` otherwise
    """
    # probe by looking for the existence of a core api descriptor file
    return os.path.exists(_get_core_descriptor_file(pipeline_config_path))


def is_localized(pipeline_config_path):
    """
    Returns true if the pipeline configuration contains a localized API
    
    :param pipeline_config_path: path to a pipeline configuration root folder
    :returns: true if localized, false if not
    """
    # first, make sure that this path is actually a pipeline configuration
    # path. otherwise, it cannot be localized :)
    if not is_pipeline_config(pipeline_config_path):
        return False

    return is_core_install_root(pipeline_config_path)


def is_core_install_root(path):
    """
    Returns true if the current path is a valid core API install root
    """
    # look for a localized API by searching for a _core_upgrader.py file
    api_file = os.path.join(path, "_core_upgrader.py")
    return os.path.exists(api_file)


def is_pipeline_config(pipeline_config_path):
    """
    Returns true if the path points to the root of a pipeline configuration
    
    :param pipeline_config_path: path to a pipeline configuration root folder
    :returns: true if pipeline config, false if not
    """
    # probe by looking for the existence of a key config file.
    config_folder = os.path.join(pipeline_config_path, "config")
    return StorageRoots.file_exists(config_folder)


def get_metadata(pipeline_config_path):
    """
    Loads the pipeline config metadata (the pipeline_configuration.yml) file from disk.
    
    :param pipeline_config_path: path to a pipeline configuration root folder
    :returns: deserialized content of the file in the form of a dict.
    """

    # now read in the pipeline_configuration.yml file
    cfg_yml = os.path.join(
        pipeline_config_path,
        "config",
        "core",
        constants.PIPELINECONFIG_FILE
    )

    try:
        data = yaml_cache.g_yaml_cache.get(cfg_yml)
        if data is None:
            raise Exception("File contains no data!")
    except Exception as e:
        raise TankError("Looks like a config file is corrupt. Please contact "
                        "support! File: '%s' Error: %s" % (cfg_yml, e))

    # DD Hackery: Get the project from DD_SHOW instead of from yaml file
    if not data.get("pc_id", None):

        # Get the shotgun connection object
        sg = get_sg_connection()

        # First check if we are in a show environment
        dd_show = os.environ.get("DD_SHOW", None)
        if dd_show:

            # Default PipelineConfiguration name is "Primary"
            pc_name = data.get("pc_name", "Primary")

            # Get the PipelineConfiguration for this show
            filters = [["code", "is", pc_name], ["project.Project.tank_name", "is", dd_show]]

            try:
                pc_entity = sg.find_one("PipelineConfiguration", filters, ["project"])
                if pc_entity is None:
                    raise TankError

                data["project_name"]    = pc_entity["project"].get("name")
                data["project_id"]      = pc_entity["project"].get("id")
                data["pc_id"]           = pc_entity.get("id")
                data["pc_name"]         = pc_name

            except TankError as e:
                logger.warning("Cannot find PipelineConfiguration for show: '%s'. " \
                    "Falling back on Site PipelineConfiguration." % dd_show)
                pass

        # Else return the Site PipelineConfiguration
        if not data.get("pc_id", None):

            # Get the PipelineConfiguration, filtered by ID 1
            pc_entity = sg.find_one("PipelineConfiguration", [["id", "is", 1]], ["code"])
            if pc_entity is None:
                logger.warning("Cannot find Site PipelineConfiguration.")
                data["pc_id"]           = 1
                data["pc_name"]         = constants.PRIMARY_PIPELINE_CONFIG_NAME
                return data

            data["pc_id"]           = pc_entity.get("id")
            data["pc_name"]         = pc_entity.get("code")

    return data


####################################################################################################################
# Core API resolve utils

def get_core_descriptor(pipeline_config_path, shotgun_connection, bundle_cache_fallback_paths=None):
    """
    Returns a descriptor object for the uri/dict defined in the config's
    ``core_api.yml`` file (if it exists).

    If the config does not define a core descriptor file, then ``None`` will be
    returned.

    :param str pipeline_config_path: The path to the pipeline configuration
    :param shotgun_connection: An open connection to shotgun
    :param bundle_cache_fallback_paths: bundle cache search path

    :return: A core descriptor object
    """

    # avoid circular dependencies
    from .descriptor import (
        Descriptor,
        create_descriptor,
        is_descriptor_version_missing
    )

    descriptor_file_path = _get_core_descriptor_file(pipeline_config_path)

    if not os.path.exists(descriptor_file_path):
        return None

    # the core_api.yml contains info about the core:
    #
    # location:
    #    name: tk-core
    #    type: app_store
    #    version: v0.16.34

    logger.debug("Found core descriptor file '%s'" % descriptor_file_path)

    # read the file first
    fh = open(descriptor_file_path, "rt")
    try:
        data = yaml.load(fh)
        core_descriptor_dict = data["location"]
    except Exception as e:
        raise TankError(
            "Cannot read invalid core descriptor file '%s': %s" %
            (descriptor_file_path, e)
        )
    finally:
        fh.close()

    # we have a core descriptor specification. Get a descriptor object for it
    logger.debug(
        "Config has a specific core defined in core/core_api.yml: %s" %
        core_descriptor_dict,
    )

    # when core is specified, check if it defines a specific version or not
    use_latest = is_descriptor_version_missing(core_descriptor_dict)

    return create_descriptor(
        shotgun_connection,
        Descriptor.CORE,
        core_descriptor_dict,
        fallback_roots=bundle_cache_fallback_paths or [],
        resolve_latest=use_latest
    )


def get_path_to_current_core():
    """
    Returns the local path of the currently executing code, assuming that this code is 
    located inside a standard toolkit install setup. If the code that is running is part
    of a localized pipeline configuration, the pipeline config root path
    will be returned, otherwise a 'studio' root will be returned.
    
    This method may not return valid results if there has been any symlinks set up as part of
    the install structure.
    
    :returns: string with path
    """
    return prez.derive(__file__).path


def _create_installed_config_descriptor(pipeline_config_path):
    """
    Creates an InstalledConfigurationDescriptor for the pipeline configuration
    at the given location.

    :param str pipeline_config_path: Path to the installed pipeline configuration.

    :returns: An :class:`sgtk.descriptor.InstalledConfigurationDescriptor` instance.
    """
    # Do a local import to avoid circular imports. This happens because descriptor_installed_config
    # and pipelineconfig_utils import each other. At some point we will refactor the functionality from
    # this file on the ConfigDescriptor objects and these circular includes won't be necessary anymore.
    from .descriptor import Descriptor, create_descriptor
    return create_descriptor(
        get_deferred_sg_connection(),
        Descriptor.INSTALLED_CONFIG,
        dict(path=pipeline_config_path, type="path")
    )


def get_core_python_path_for_config(pipeline_config_path):
    """
    Returns the location of the Toolkit library associated with the given pipeline configuration.

    :param pipeline_config_path: path to a pipeline configuration

    :returns: Path to location where the Toolkit Python library associated with the config resides.
    :rtype: str
    """
    return os.path.join(get_core_path_for_config(pipeline_config_path), "python")


def get_core_path_for_config(pipeline_config_path):
    """
    Returns the core api install location associated with the given pipeline configuration.

    In the case of a localized PC, it just returns the given path.
    Otherwise, it resolves the location via the core_xxxx.cfg files.

    :param pipeline_config_path: path to a pipeline configuration

    :returns: Path to the studio location root or pipeline configuration root or None if not resolved
    """
    if is_localized(pipeline_config_path):
        # first, try to locate an install local to this pipeline configuration.
        # this would find any localized APIs.
        return pipeline_config_path

    project_name = get_metadata(pipeline_config_path).get("project_name", "site")
    return get_core_install_location(project_name)

def get_sgtk_module_path():
    """
    Returns the path to ``sgtk`` module. This path can be used by another process to update its
    ``PYTHONPATH`` and use the same ``sgtk`` module as the process invoking this method.

    For example, if the Toolkit core was installed at
    ``/home/user/.shotgun/bundle_cache/app_store/tk-core/v0.18.94``, the method would return
    ``/home/user/.shotgun/bundle_cache/app_store/tk-core/v0.18.94/python``.

    .. note:: This method can be invoked for cores that are part of a pipeline configuration, that
              lives inside the bundle cache or a development copy of the core.

    :returns: Path to the ``sgtk`` module on disk.
    """
    return os.path.join(get_path_to_current_core(), "python")


def get_python_interpreter_for_config(pipeline_config_path):
    """
    Retrieves the path to the Python interpreter for a given pipeline configuration
    path.

    Each pipeline configuration has three (one for Windows, one for macOS and one for Linux) interpreter
    files that provide a path to the Python interpreter used to launch the ``tank``
    command.

    If you require a `python` executable to launch a script that will use a pipeline configuration, it is
    recommended its associated Python interpreter.

    .. deprecated:: v0.18.94
        You can now access the content of the ``interpreter_*.yml``
        through the :meth:`ConfigDescriptor.python_interpreter` property.

        >>> engine = sgtk.platform.current_engine()
        >>> descriptor = engine.sgtk.configuration_descriptor
        >>> print descriptor.python_interpreter

    :param str pipeline_config_path: Path to the pipeline configuration root.

    :returns: Path to the Python interpreter for that configuration.
    :rtype: str

    :raises ~sgtk.descriptor.TankInvalidInterpreterLocationError: Raised if the interpreter in the interpreter file doesn't
        exist.
    :raises TankFileDoesNotExistError: Raised if the interpreter file can't be found.
    :raises TankNotPipelineConfigurationError: Raised if the pipeline configuration path is not
        a pipeline configuration.
    :raises TankInvalidCoreLocationError: Raised if the core location specified in core_xxxx.cfg
        does not exist.
    """
    return _create_installed_config_descriptor(pipeline_config_path).python_interpreter


def resolve_all_os_paths_to_core(core_path):
    """
    Given a core path on the current os platform, 
    return paths for all platforms, 
    as cached in the install_locations system file

    :returns: dictionary with keys linux2, darwin and win32
    """
    # @todo - refactor this to return a ShotgunPath
    return _get_install_locations(core_path).as_system_dict()


def resolve_all_os_paths_to_config(pc_path):
    """
    Given a pipeline configuration path on the current os platform, 
    return paths for all platforms, as cached in the install_locations system file

    :returns: ShotgunPath object
    """
    return _get_install_locations(pc_path)


def get_core_install_location(path_or_project=None):
    """
    Given a path on disk or project_name, return the location of the core api location
    """
    return get_package_install_location('sgtk_core', path_or_project)
    

def get_config_install_location(path_or_project=None):
    """
    Given a path on disk or project_name, return the location of the core api location
    """
    return get_package_install_location('sgtk_config', path_or_project)
    
    
def get_package_install_location(package_name, path_or_project=None):
    """
    Given a path on disk or project_name, return the location of a given package
    """
    package_key = (package_name, path_or_project)

    # Check if we've processed this package before before
    # and if so return from cache
    package_path = g_package_cache.get(package_key)
    if package_path:
        return package_path

    # If the input is a path, first see if it is a distribution path
    if path_or_project and os.path.exists(path_or_project):
        try:
            # Attempt to derive a distribution from the path
            distro = prez.derive(path_or_project)

            # Ensure that the resulting distro corresponds to the requested package
            if distro.project != package_name:
                raise TankError("Specified path %s does not correspond to package: %s" % (path_or_project, package_name))

            # Add package path to cache
            g_package_cache.add(package_key, distro.path)

            # Specified path is a distribution, so just return it
            return distro.path

        except prez.NotFoundError:
            # This isn't a distribution path...which is fine
            pass

    # Get the current configuration
    config = prez.Configuration.current()

    # Get the current environment
    env = prez.Environment.forConfiguration(config)

    # TODO: Remove this conditional after #118805 is resolved
    # First check if there is a with override for this package
    spec = os.environ.get("DD_WITH_OVERRIDE") or ""
    with_overrides = dict(x.partition("=")[::2] for x in spec.split(",") if x != "")

    # If there is a "with" override, get the corresponding version distribution
    if with_overrides.get(package_name):
        package_version = prez.Version.parse(with_overrides[package_name])
        distro = env.getDistribution(package_name, package_version)

    # Else resolve to find the current environment's distribution
    else:
        package_version = None
        distro = env.resolveDistribution(package_name)

    # If we have a resolved distro...
    if distro:
        # ...and it comes from a local workarea, this always wins
        if prez.Level.parse(prez.derive(distro.path).source.name).isWorkarea:

            # Add package path to cache
            g_package_cache.add(package_key, distro.path)

            # Return the path to the resolved distribution
            return distro.path

    # If a level_spec was provided, attempt to derive the corresponding environment
    if path_or_project:

        # If path_or_project is set to "site" keyword, use the facility level
        if path_or_project == "site":
            level_spec = prez.Level.facility()

        # Else if it is a path, derive the level
        elif os.path.exists(path_or_project):
            level_spec = prez.Level.derive(path_or_project)

        # Else assume it is a project name
        else:
            level_spec = prez.Level.parse(path_or_project.upper())

        # Update the config for the new level_spec
        config.replace(level=level_spec)

        # Get the environment for the updated Configuration
        env = prez.Environment.forConfiguration(config)

        # If the version isn't set via a with override...
        if not package_version:
            # Resolve the version pin for the new environment
            package_version = env.resolvePin(package_name).version

        # Get the distribution for this environment
        distro = env.getDistribution(package_name, package_version)

    # Ensure we have a valid distribution
    if not distro:
        raise TankError("Cannot get distribution %s-%s for env %s" % (package_name, package_version, env))

    # Add package path to cache
    g_package_cache.add(package_key, distro.path)

    # Return the path to the resolved distribution
    return distro.path


def _get_install_locations(path):
    """
    Given a pipeline configuration OR core location, return paths on all platforms.
    
    :param path: Path to a pipeline configuration on disk.
    :returns: ShotgunPath object
    """
    # basic sanity check
    if not os.path.exists(path):
        raise TankError("The core path '%s' does not exist on disk!" % path)
    
    # for other platforms, read in install_location
    location_file = os.path.join(path, "config", "core", "install_location.yml")

    # load the config file
    try:
        location_data = yaml_cache.g_yaml_cache.get(location_file, deepcopy_data=False) or {}
    except Exception as error:
        raise TankError("Cannot load core config file '%s'. Error: %s" % (location_file, error))

    # do some cleanup on this file - sometimes there are entries that say "undefined"
    # or is just an empty string - turn those into null values
    linux_path = location_data.get("Linux")
    macosx_path = location_data.get("Darwin")
    win_path = location_data.get("Windows")
    
    # this file may contain environment variables. Try to expand these.
    if linux_path:
        linux_path = os.path.expandvars(linux_path)     
    if macosx_path:
        macosx_path = os.path.expandvars(macosx_path) 
    if win_path:
        win_path = os.path.expandvars(win_path) 

    # lastly, sanity check the paths - sometimes these files contain non-path
    # values such as "None" or "unknown"
    if not linux_path or not linux_path.startswith("/"):
        linux_path = None
    if not macosx_path or not macosx_path.startswith("/"):
        macosx_path = None
    if not win_path or not (win_path.startswith("\\") or win_path[1] == ":"):
        win_path = None

    # sanitize data into a ShotgunPath and return data
    return ShotgunPath(win_path, linux_path, macosx_path)


####################################################################################################################
# utils for determining core version numbers

def get_currently_running_api_version():
    """
    Returns the version number string for the core API, 
    based on the code that is currently executing.
    
    :returns: version string, e.g. 'v1.2.3'. 'unknown' if a version number cannot be determined.
    """
    # read this from info.yml
    info_yml_path = os.path.join(get_path_to_current_core(), "info.yml")
    return _get_version_from_manifest(info_yml_path)


def get_core_api_version(core_install_root):
    """
    Returns the version string for the core api associated with this config.
    This method is 'forgiving' and in the case no associated core API can be 
    found for this location, 'unknown' will be returned rather than 
    an exception raised. 

    :param core_install_root: Path to a core installation root, either the root of a pipeline
                              configuration, or the root of a "bare" studio code location.
    :returns: version str e.g. 'v1.2.3', 'unknown' if no version could be determined. 
    """
    # now try to get to the info.yml file to get the version number
    info_yml_path = os.path.join(core_install_root, "info.yml")
    return _get_version_from_manifest(info_yml_path)

    
def _get_version_from_manifest(info_yml_path):
    """
    Helper method. 
    Returns the version given a manifest.
    
    :param info_yml_path: path to manifest file.
    :returns: Always a string, 'unknown' if data cannot be found
    """
    try:
        data = yaml_cache.g_yaml_cache.get(info_yml_path) or {}
        data = str(data.get("version", "unknown"))
    except Exception:
        data = "unknown"

    return data


def _get_core_descriptor_file(pipeline_config_path):
    """
    Helper method. Returns the path to the config's core_api.yml file.
    (May not exist)

    :param pipeline_config_path: path to the pipeline configuration on disk
    :return: A string path to the core_api.yml file within the config.
    """
    return os.path.join(
        pipeline_config_path,
        "config",
        "core",
        constants.CONFIG_CORE_DESCRIPTOR_FILE
    )
