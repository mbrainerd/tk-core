# Copyright (c) 2013 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.

import sys, os, logging

import sgtk
from sgtk import constants
from sgtk import LogManager

# the logger used by this file is sgtk.tank_cmd
app_name = "shotgun_publish"
logger = LogManager.get_logger(app_name)

def init_logging():
    """
    Initialize logging
    """
    global logger, formatter

    # set up std toolkit logging to file
    LogManager().initialize_base_file_handler(app_name)

    # set up output of all sgtk log messages to stdout
    handler = logging.StreamHandler(sys.stdout)
    LogManager().initialize_custom_handler(handler)

    # check if there is a --debug flag anywhere in the args list.
    # in that case turn on debug logging and remove the flag
    if os.environ.get("DD_DEBUG"):
        LogManager().global_debug = True
        logger.debug("")
        logger.debug("A log file can be found in %s" % LogManager().log_folder)
        logger.debug("")

    logger.debug("Running main from %s" % __file__)
    return handler


def init_user_credentials():
    """
    Initialize the user credentials for Toolkit
    """
    # Initialize shotgun authentication
    core_dm = sgtk.authentication.CoreDefaultsManager()
    shotgun_authenticator = sgtk.authentication.ShotgunAuthenticator(core_dm)
    user = shotgun_authenticator.get_user()
    if user.are_credentials_expired():
        # If they are, we will clear them from the session cache...
        shotgun_authenticator.clear_default_user()
        user = shotgun_authenticator.get_user()

    sgtk.set_authenticated_user(user)


def main():
    """
    Do stuff
    """
    # Initialize logging
    log_handler = init_logging()

    # Initialize user credentials
    init_user_credentials()

    # Create an API instance
    tk = sgtk.sgtk_from_path(sgtk.pipelineconfig_utils.get_config_install_location())

    # If we're opening a new file, get context from cwd
    ctx = tk.context_from_path(os.getcwd())

    # Cannot launch engine if running in site mode
    if tk.pipeline_configuration.is_site_configuration():
        logger.info("Running using site configuration. Skipping filesystem update.")

    else:
        if tk.pipeline_configuration.get_shotgun_path_cache_enabled():
            tk.synchronize_filesystem_structure()

        # Get the appropriate entity
        ctx_entity = ctx.task or ctx.entity or ctx.project

        # Run filesystem creation
        if ctx_entity:
            tk.create_filesystem_structure(ctx_entity.get("type"), ctx_entity.get("id"), app_name)

    try:
        engine = sgtk.platform.start_engine("tk-shell", tk, ctx)
    except Exception as e:
        logger.error("Could not start engine: %s" % str(e))
        if os.environ.get("DD_DEBUG"):
            import pdb; pdb.post_mortem()
        raise
        
    # If we have an engine, then hand off logging responsibilities
    # to it and remove the startup log handler
    LogManager().root_logger.removeHandler(log_handler)

    try:
        return engine.execute_command("Publish...", [])
    except Exception as e:
        logger.error("Could not start app: %s" % str(e))
        if os.environ.get("DD_DEBUG"):
            import pdb; pdb.post_mortem()
        raise

if __name__ == "__main__":
    main()
