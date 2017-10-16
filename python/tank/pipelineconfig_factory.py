# Copyright (c) 2014 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.

import os
import collections
import logging
import cPickle as pickle

from .errors import TankError
from . import constants
from . import LogManager
from .util import shotgun
from .util import filesystem
from .util import ShotgunPath
from . import constants
from . import pipelineconfig_utils
from .pipelineconfig import PipelineConfiguration
from .util import LocalFileStorageManager

log = LogManager.get_logger(__name__)

def from_entity(entity_type, entity_id):
    """
    Factory method that constructs a pipeline configuration given a Shotgun Entity.

    Note! Because this is a factory method which is part of the initialization of
    Toolkit, at the point of execution, very little state has been established.
    Because the pipeline configuration and project is not know at this point,
    conventional configuration data and hooks cannot be accessed.

    :param entity_type: Shotgun Entity type
    :param entity_id: Shotgun id
    :returns: Pipeline Configuration object
    """
    try:
        pc = _from_entity(entity_type, entity_id, force_reread_shotgun_cache=False)
    except TankError:
        # lookup failed! This may be because there are missing items
        # in the cache. For failures, try again, but this time
        # force re-read the cache (e.g connect to shotgun)
        # if the previous failure was due to a missing item
        # in the cache,
        pc = _from_entity(entity_type, entity_id, force_reread_shotgun_cache=True)

    return pc


def _from_entity(entity_type, entity_id, force_reread_shotgun_cache):
    """
    Factory method that constructs a pipeline configuration given a Shotgun Entity.
    This method contains the implementation payload.

    :param entity_type: Shotgun Entity type
    :param entity_id: Shotgun id
    :param force_reread_shotgun_cache: Should the cache be force re-populated?
    :returns: Pipeline Configuration object
    """

    # first see if we can resolve a project id from this entity
    project_info = __get_project_info(entity_type, entity_id, force_reread_shotgun_cache)

    # now given the project id, find the pipeline configurations
    if project_info is None:
        raise TankError("Cannot find a valid %s with id %s in Shotgun! "
                        "Please ensure that the object exists "
                        "and that it has been linked up to a Toolkit "
                        "enabled project." % (entity_type, entity_id))

    # We use the project name for path resolution
    project_name = project_info.get("name", "site")

    # Get the path to the pipeline configuration for this path
    pc_path = pipelineconfig_utils.get_config_install_location(project_name)
    if pc_path is None:
        raise TankError("There is no pipeline configuration associated with this project: '%s'" % project_name)

    return PipelineConfiguration(pc_path)


def from_path(path):
    """
    Factory method that constructs a pipeline configuration given a path on disk.

    Note! Because this is a factory method which is part of the initialization of
    Toolkit, at the point of execution, very little state has been established.
    Because the pipeline configuration and project is not know at this point,
    conventional configuration data and hooks cannot be accessed.

    :param path: Path to a pipeline configuration or associated project folder
    :returns: Pipeline Configuration object
    """
    if not isinstance(path, basestring):
        raise TankError("Cannot create a configuration from path '%s' - path must be a string!" % path)

    path = os.path.abspath(path)

    # make sure folder exists on disk
    if not os.path.exists(path):
        # there are cases when a pipeline config is being created
        # from a _file_ which does not yet exist on disk. To try to be
        # reasonable with this case, try this check on the
        # parent folder of the path as a last resort.
        parent_path = os.path.dirname(path)
        if os.path.exists(parent_path):
            path = parent_path
        else:
            raise TankError("Cannot create a configuration from path '%s' - the path does "
                            "not exist on disk!" % path)

    # first see if someone is passing the path to an actual pipeline configuration
    if pipelineconfig_utils.is_pipeline_config(path):
        return PipelineConfiguration(path)

    # Get the path to the pipeline configuration for this path
    pc_path = pipelineconfig_utils.get_config_install_location(path)
    if pc_path is None:
        raise TankError("There is no pipeline configuration associated with this path:\n'%s'" % path)

    return PipelineConfiguration(pc_path)


#################################################################################################################
# methods relating to maintaining a small cache to speed up initialization

def __get_project_info(entity_type, entity_id, force=False):
    """
    Connects to Shotgun and retrieves the project id for an entity.

    Uses a cache if possible.

    :param entity_type: Shotgun Entity type
    :param entity_id: Shotgun entity id
    :param force: Force read values from Shotgun
    :returns: project id (int) or None if not found
    """
    CACHE_KEY = "%s_%s" % (entity_type, entity_id)

    if force == False:
        # try to load cache first
        # if that doesn't work, fall back on shotgun
        cache = _load_lookup_cache()
        if cache and cache.get(CACHE_KEY):
            # cache hit!
            return cache.get(CACHE_KEY)

    # ok, so either we are force recomputing the cache or the cache wasn't there
    sg = shotgun.get_sg_connection()

    # get all local storages for this site
    entity_data = sg.find_one(entity_type, [["id", "is", entity_id]], ["project"])

    if entity_data and "project" in entity_data:
        _add_to_lookup_cache(CACHE_KEY, entity_data["project"])
        return entity_data["project"]


def _load_lookup_cache():
    """
    Load lookup cache file from disk.

    :returns: cache cache, as constructed by the _add_to_lookup_cache method
    """
    cache_file = _get_cache_location()
    cache_data = {}

    try:
        fh = open(cache_file, "rb")
        try:
            cache_data = pickle.load(fh)
        finally:
            fh.close()
    except Exception as e:
        # failed to load cache from file. Continue silently.
        log.debug(
            "Failed to load lookup cache %s. Proceeding without cache. Error: %s" % (cache_file, e)
        )

    return cache_data

@filesystem.with_cleared_umask
def _add_to_lookup_cache(key, data):
    """
    Add a key to the lookup cache. This method will silently
    fail if the cache cannot be operated on.

    :param key: Dictionary key for the cache
    :param data: Data to associate with the dictionary key
    """

    # first load the content
    cache_data = _load_lookup_cache()
    # update
    cache_data[key] = data
    # and write out the cache
    cache_file = _get_cache_location()

    try:
        filesystem.ensure_folder_exists(os.path.dirname(cache_file))

        # write cache file
        fh = open(cache_file, "wb")
        try:
            pickle.dump(cache_data, fh)
        finally:
            fh.close()
        # and ensure the cache file has got open permissions
        os.chmod(cache_file, 0o666)

    except Exception as e:
        # silently continue in case exceptions are raised
        log.debug(
            "Failed to add to lookup cache %s. Error: %s" % (cache_file, e)
        )


def _get_cache_location():
    """
    Get the location of the initializtion lookup cache.
    Just computes the path, no I/O.

    :returns: A path on disk to the cache file
    """
    # optimized version of creating an sg instance and then calling sg.base_url
    # this is to avoid connecting to shotgun if possible.
    sg_base_url = shotgun.get_associated_sg_base_url()
    root_path = LocalFileStorageManager.get_site_root(sg_base_url, LocalFileStorageManager.CACHE)
    return os.path.join(root_path, constants.TOOLKIT_INIT_CACHE_FILE)
