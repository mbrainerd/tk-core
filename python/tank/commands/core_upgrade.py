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
Tank command allowing to do core updates.
"""

from __future__ import with_statement

from ..errors import TankError
from .action_base import Action

import os
import sys
import textwrap
import optparse
import copy

from ..util import shotgun
from .. import pipelineconfig_utils
from . import console_utils
from ..util.version import is_version_newer, is_version_head

from tank_vendor import yaml


# FIXME: This should be refactored into something that can be used by other commands.
class TkOptParse(optparse.OptionParser):
    """
    Toolkit option parser for tank commands. It makes the interface and messages compatible with how Toolkit
    displays errors.
    """

    def __init__(self, *args, **kwargs):
        """
        Constructor.
        """
        # Don't generate the --help options, since --help is already eaten up by tank_cmd.py
        kwargs = copy.copy(kwargs)
        kwargs["add_help_option"] = False
        optparse.OptionParser.__init__(self, *args, **kwargs)
        # optparse uses argv[0] for the program, but users use the tank command instead, so replace
        # the program.
        self.prog = "tank"

    def error(self, msg):
        """
        :param msg: Error message for the TankError.

        :raises TankError: Throws a TankError with the message passed in.
        """
        raise TankError(msg)


class CoreUpdateAction(Action):
    """
    Action to update the Core API code that is associated with the currently running code.
    """

    def __init__(self):
        """
        Constructor.
        """
        Action.__init__(self,
                        "core",
                        Action.GLOBAL,
                        "Updates your Toolkit Core API to a different version.",
                        "Configuration")

        # this method can be executed via the API
        self.supports_api = True

        ret_val_doc = "Returns a dictionary with keys status (str) optional keys. The following status codes "
        ret_val_doc += "are returned: 'up_to_date' if no update was needed, 'updated' if an update was "
        ret_val_doc += "applied and 'update_blocked' if an update was available but could not be applied. "
        ret_val_doc += "For the 'updated' status, data will contain new_version key with the version "
        ret_val_doc += "number of the core that was updated to. "
        ret_val_doc += "For the 'update_blocked' status, data will contain a reason key containing an explanation."

        self.parameters = {"return_value": {"description": ret_val_doc, "type": "dict" }}

    def _parse_arguments(self, parameters):
        """
        Parses the list of arguments from the command line.

        :param parameters: The content of argv that hasn't been processed by the tank command.

        :returns: The core version. None if --version wasn't specified.
        """
        parser = TkOptParse()
        parser.set_usage(optparse.SUPPRESS_USAGE)
        parser.add_option("-v", "--version", type="string", default=None)
        parser.add_option("-s", "--source", type="string", default=None)
        parser.add_option("-b", "--backup", action="store_true", default=False)
        options, args = parser.parse_args(parameters)

        if options.version is not None and not options.version.startswith("v"):
            parser.error("version string should always start with 'v'")
        return (options.version, options.source, options.backup)

    def run_noninteractive(self, log, parameters):
        """
        Tank command API accessor.
        Called when someone runs a tank command through the core API.

        :param log: std python logger
        :param parameters: dictionary with tank command parameters
        """
        core_version = parameters[0] if len(parameters) else None
        core_source = parameters[1] if len(parameters) > 1 else None
        backup_core = parameters[2] if len(parameters) > 2 else False

        return self._run(log, True, core_version, core_source, backup_core)

    def run_interactive(self, log, args):
        """
        Tank command accessor

        :param log: std python logger
        :param args: command line args
        """
        (core_version, core_source, backup_core) = self._parse_arguments(args)

        self._run(log, False, core_version, core_source, backup_core)

    def _run(self, log, suppress_prompts, core_version, core_source, backup_core):
        """
        Actual execution payload.

        :param log: std python logger
        :param suppress_prompts: If False, user will be prompted to accept or reject the core update.
        :param core_version: Version to update the core to. If None, updates the core to the latest version.
        """

        # get the core api root of this installation by looking at the cwd first
        # then at the relative location of the running code.
        if pipelineconfig_utils.is_core_install_root(os.getcwd()):
            self._core_install_root = os.getcwd()
        else:
            self._core_install_root = pipelineconfig_utils.get_path_to_current_core()

        self._log = log
        self._log.info("")
        self._log.info("Welcome to the Shotgun Pipeline Toolkit update checker!")
        self._log.info("This script will check if the Toolkit Core API installed")
        self._log.info("in %s" % self._core_install_root)
        self._log.info("is up to date.")
        self._log.info("")
        self._log.info("")

        self._log.info("Please note that if this is a shared Toolkit Core used by more than one project, "
                 "this will affect all of the projects that use it. If you want to test a Core API "
                 "update in isolation, prior to rolling it out to multiple projects, we recommend "
                 "creating a special *localized* pipeline configuration.")
        self._log.info("")
        self._log.info("For more information, please see the Toolkit documentation:")
        self._log.info("https://support.shotgunsoftware.com/entries/96141707")
        self._log.info("https://support.shotgunsoftware.com/entries/96142347")
        self._log.info("")

        self._current_core_desc = TankCoreUpdater.get_current_core_descriptor(self._log, self._core_install_root)
        current_source = self._current_core_desc.get_dict()['type']
        current_version = self._current_core_desc.version
        self._log.info("You are currently running SGTK Core %s from '%s'" % (current_version, current_source))

        # if core_source not specified, assume it is the same as current source
        check_app_store = False
        if core_source is None:
            if current_source == 'app_store':
                core_source = current_source
            else:
                core_source = self._current_core_desc.get_dict()['path']

            # if core_version is not specified and current_source
            # is not 'app_store', also check 'app_store'
            if core_version is None and \
               current_source is not 'app_store':
                check_app_store = True

        return self._upgrade_core(core_version, core_source, suppress_prompts, backup_core, check_app_store)


    def _upgrade_core(self, core_version, core_source, suppress_prompts, backup_core, check_app_store):
        """
        Internal method for running the upgrade
        """
        return_status = {"status": "unknown"}

        upgrade_core_desc = TankCoreUpdater.get_upgrade_core_descriptor(self._log, core_version, core_source)
        if upgrade_core_desc is None:
            raise TankError("Cannot determine descriptor for specified upgrade version!")
        upgrade_source = upgrade_core_desc.get_dict()['type']
        upgrade_version = upgrade_core_desc.version

        installer = TankCoreUpdater(self._core_install_root, 
                                    self._log,
                                    self._current_core_desc,
                                    upgrade_core_desc,
                                    backup_core)

        status = installer.get_update_status()
        if status == TankCoreUpdater.UP_TO_DATE:

            # If we don't have a newer local version, check the app_store
            if check_app_store:
                self._log.info("Could not find newer version in '%s'. Checking app_store..." % core_source)
                return self._upgrade_core(None, 'app_store', suppress_prompts, backup_core, False)

            self._log.info("No need to update the Toolkit Core API at this time!")
            return_status = {"status": "up_to_date"}

        elif status == TankCoreUpdater.UPDATE_IS_OLDER:
            self._log.info("Requested version %s found in '%s' is older than current version." % (upgrade_version, upgrade_source))

        elif status == TankCoreUpdater.UPDATE_IS_NEWER:
            self._log.info("Newer version %s found in '%s'!" % (upgrade_version, upgrade_source))

        (summary, url) = upgrade_core_desc.changelog
        self._log.info("")
        self._log.info("Change Summary:")
        for x in textwrap.wrap(summary, width=60):
            self._log.info(x)
        self._log.info("")
        self._log.info("Detailed Release Notes:")
        self._log.info("%s" % url)
        self._log.info("")
        self._log.info("Please note that if this is a shared core used by more than one project, "
                 "this will affect the other projects as well.")
        self._log.info("")

        if suppress_prompts or console_utils.ask_yn_question("Update to this version of the Core API?"):

            # Check we meet the required minimum shotgun version for this update
            status = installer.check_sg_version_req()
            if status == TankCoreUpdater.UPDATE_BLOCKED_BY_SG:
                req_sg = upgrade_core_desc.version_constraints["min_sg"]
                msg = (
                    "%s version of core requires a more recent version (%s) of Shotgun!" % (
                        "The newest" if core_version is None else "The requested",
                        req_sg
                    )
                )
                self._log.error(msg)
                return_status = {"status": "update_blocked", "reason": msg}

            elif status == TankCoreUpdater.UPDATE_POSSIBLE:

                # install it!
                installer.do_install()

                self._log.info("")
                self._log.info("")
                self._log.info("----------------------------------------------------------------")
                self._log.info("The Toolkit Core API has been updated!")
                self._log.info("")
                self._log.info("")
                self._log.info("Please note the following:")
                self._log.info("")
                self._log.info("- You need to restart any applications (such as Maya or Nuke)")
                self._log.info("  in order for them to pick up the API update.")
                self._log.info("")
                self._log.info("- Please close this shell, as the update process")
                self._log.info("  has replaced the folder that this script resides in")
                self._log.info("  with a more recent version. ")
                self._log.info("")
                self._log.info("----------------------------------------------------------------")
                self._log.info("")
                return_status = {"status": "updated", "new_version": upgrade_version}

            else:
                raise TankError("Unknown Update state!")
        else:
           self._log.info("The Shotgun Pipeline Toolkit will not be updated.")

        return return_status


class TankCoreUpdater(object):
    """
    Class which handles the update of the core API.
    """

    # possible update status states
    (
        UP_TO_DATE,                   # all good, no update necessary
        UPDATE_IS_OLDER,              # the requested update is older than the currently installed version
        UPDATE_IS_NEWER,              # the requested update is newer than the currently installed version
        UPDATE_POSSIBLE,              # more recent version exists
        UPDATE_BLOCKED_BY_SG          # more recent version exists but SG version is too low.
    ) = range(5)

    def __init__(self, install_folder_root, logger, old_core_descriptor, new_core_descriptor, backup_core=False):
        """
        Constructor

        :param install_folder_root: The path to the installation to check. This is either a localized
                                   Pipeline Configuration or a studio code location (omit the install folder).
                                   Because we are passing this parameter in explicitly, the currently running
                                   code base does not have to be related to the code base that is being updated,
                                   e.g. you can run the updater as a totally separate thing.
        :param logger: Logger to send output to.
        :param core_version: Version of the core to update to. If None, the core will be updated to the latest
                             version. Defaults to None.
        """
        self._log = logger
        self._backup_core = backup_core

        self._core_install_root = install_folder_root
        self._old_core_descriptor = old_core_descriptor
        self._new_core_descriptor = new_core_descriptor

    @classmethod
    def get_current_core_descriptor(cls, log, core_install_root):
        """
        Returns the descriptor for the currently installed Toolkit API core
        """
        from ..descriptor import Descriptor, create_descriptor

        local_sg = shotgun.get_sg_connection()

        config_path = os.path.join(core_install_root, 'config')
        config_descriptor = create_descriptor(local_sg, Descriptor.CONFIG,
                                    {'type' : 'path', 'path' : config_path})

        # Get the core descriptor dict from config/core/core_api.yml
        core_uri_or_dict = config_descriptor.associated_core_descriptor

        if core_uri_or_dict is None:
            # Assume app_store and try and get version from info.yml
            log.debug("core_api.yml does not exist. Reading info.yml instead.")
            version = pipelineconfig_utils.get_core_api_version(core_install_root)

            return create_descriptor(local_sg, Descriptor.CORE,
                            {'name' : 'tk-core',
                             'type' : 'app_store',
                             'version' : version}
                    )

        # we have an exact core descriptor. Get a descriptor for it
        log.debug("Core descriptor defined in core/core_api.yml: %s" % core_uri_or_dict)

        return create_descriptor(local_sg, Descriptor.CORE, core_uri_or_dict)

    @classmethod
    def get_upgrade_core_descriptor(cls, log, core_version=None, core_source=None):
        """
        Returns the descriptor for the upgradeable Toolkit API core
        """
        from ..descriptor import Descriptor, create_descriptor

        local_sg = shotgun.get_sg_connection()

        # if core_source not specified, assume app_store
        if core_source is None:
            core_source = 'app_store'

        descriptor_dict = { 'name' : 'tk-core' }
        if core_source == 'app_store':
            descriptor_dict['type'] = 'app_store'
        elif core_source.endswith(".git"):
            descriptor_dict['type'] = 'git'
            descriptor_dict['path'] = core_source
        else:
            if not os.path.exists(core_source):
                raise TankError("Cannot find path '%s' on disk!" % core_source)
            descriptor_dict['type'] = 'dev'
            descriptor_dict['path'] = core_source

        if core_version:
            descriptor_dict['version'] = core_version
            return create_descriptor(local_sg, Descriptor.CORE, descriptor_dict)

        return create_descriptor(local_sg, Descriptor.CORE, descriptor_dict, resolve_latest=True)

    def get_update_status(self):
        """
        Check whether we are up to date, older than, or newer than the update version.
        """
        old_version = self._old_core_descriptor.version
        new_version = self._new_core_descriptor.version
        if is_version_head(old_version):
            # head is the version number which is stored in tank core trunk
            # getting this as a result means that we are not actually running
            # a version of tank that came from the app store, but some sort
            # of dev version
            return self.UP_TO_DATE

        elif old_version == new_version:
            # running updated version already
            return self.UP_TO_DATE

        elif is_version_newer(old_version, new_version):
            # current version is newer than requested version
            return self.UPDATE_IS_OLDER

        return self.UPDATE_IS_NEWER

    def check_sg_version_req(self):
        """
        Check we meet the required minimum shotgun version for this update
        """
        # FIXME: We should cache info.yml on the appstore so we don't have
        # to download the whole bundle just to see the file.
        if not self._new_core_descriptor.exists_local():
            self._log.info("")
            self._log.info("Downloading Toolkit Core API %s from '%s'..." % 
                    (self._new_core_descriptor.version,
                     self._new_core_descriptor.get_dict()['type'])
                    )
            self._new_core_descriptor.download_local()
            self._log.info("Download completed.")

        # running an older version. Make sure that shotgun has the required version
        req_sg_version = self._new_core_descriptor.version_constraints["min_sg"]
        if req_sg_version is None:
            # no particular version required! We are good to go!
            return TankCoreUpdater.UPDATE_POSSIBLE
        else:

            # now also extract the version of shotgun currently running
            local_sg = shotgun.get_sg_connection()
            try:
                cur_sg_version = ".".join([ str(x) for x in local_sg.server_info["version"]])
            except Exception, e:
                raise TankError("Could not extract version number for shotgun: %s" % e)

            # there is a sg min version required - make sure we have that!
            if is_version_newer(req_sg_version, cur_sg_version):
                return TankCoreUpdater.UPDATE_BLOCKED_BY_SG
            else:
                return TankCoreUpdater.UPDATE_POSSIBLE

    def do_install(self):
        """
        Installs the requested core and updates core_api.yml.
        """
        self._install_core()
        self._update_core_api_descriptor()

    def _install_core(self):
        """
        Performs the actual installation of the new version of the core API
        """
        self._log.info("Now installing Toolkit Core.")

        sys.path.insert(0, self._new_core_descriptor.get_path())
        try:
            import _core_upgrader
            _core_upgrader.upgrade_tank(self._core_install_root, self._log, self._backup_core)
        except Exception, e:
            self._log.exception(e)
            raise Exception("Could not run update script! Error reported: %s" % e)

    def _update_core_api_descriptor(self):
        """
        Updates the core_api.yml descriptor file.
        """
        core_api_yaml_path = os.path.join(self._core_install_root, "config", "core", "core_api.yml")

        message = "# Shotgun Pipeline Toolkit configuration file. This file was automatically\n"\
                  "# created during the latest core update.\n"
        with open(core_api_yaml_path, "w") as f:
            f.writelines(message)
            yaml.safe_dump(
                {"location": self._new_core_descriptor.get_dict()}, f,
                default_flow_style=False
            )
