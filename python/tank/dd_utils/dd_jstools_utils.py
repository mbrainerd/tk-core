# Confidential and Proprietary Source Code
#
# This Digital Domain Productions, Inc. ("DDPI") source code, including without
# limitation any human-readable computer programming code and associated
# documentation (together "Source Code"), contains valuable confidential,
# proprietary and trade secret information of DDPI and is protected by the laws
# of the United States and other countries. DDPI may, from time to
# time, authorize specific employees to use the Source Code internally at DDPI's
# premises solely for developing, updating, and/or troubleshooting the Source
# Code. Any other use of the Source Code, including without limitation any
# disclosure, copying or reproduction, without the prior written authorization
# of DDPI is strictly prohibited.
#
# Copyright (c) [2013] Digital Domain Productions, Inc. All rights reserved.
#

#  STANDARD
import os
import stat
import shutil

#  DD
from dd.runtime import api
api.load('jstools')
import jstools

# SETUP LOGGING
from ..log import LogManager
logger = LogManager.get_logger(__name__)


def _do_makedir_with_os_makedirs(path, permissions):
    """
    Helper function
    """
    if os.path.isdir(path): return

    logger.debug("Creating folder with os.makedirs: %s", path)
    try:
        os.makedirs(path, permissions)
    except IOError, e:
        raise IOError("Failed to create folder with os.makedirs: %s %s" % (path, str(e)))


def _do_makedir_with_jstools(path):
    """
    Helper function
    """
    if os.path.isdir(path): return

    logger.debug("Creating folder with jstools.jsmk: %s", path)
    result, msg = jstools.jsmk(path)
    if not result:
        raise IOError("Failed to create folder with jstools.jsmk: %s %s" % (path, msg))


def makedir_with_jstools(path, permissions=0775):
    """
    Attempts to create directories within the jstemplate-controlled area
    """
    dd_show = os.environ.get("DD_SHOW", None)
    if dd_show:
        template = jstools.Template(dd_show)

        # If its not a valid template path, don't make it
        if not template.isValidPath(path):
            raise IOError("Path is not valid. Check your jstemplate.xml: %s" % path)

        # Use jsmk to create the template directory
        _do_makedir_with_jstools(path)

    else:
        # Else use os.makedirs to create the non template directory
        _do_makedir_with_os_makedirs(path, permissions)


def _get_permissions(path):
    """
    Retrieve the file system permissions for the file or folder in the
    given path.

    :param filename: Path to the file to be queried for permissions
    :returns: permissions bits of the file
    :raises: OSError - if there was a problem retrieving permissions for the path
    """
    return stat.S_IMODE(os.stat(path)[stat.ST_MODE])


def _do_delete_with_shutil_rmtree(path):
    """
    Helper function
    """
    def _on_rm_error(func, path, exc_info):
        """
        Error function called whenever shutil.rmtree fails to remove a file system
        item. Exceptions raised by this function will not be caught.

        :param func: The function which raised the exception; it will be:
                     os.path.islink(), os.listdir(), os.remove() or os.rmdir().
        :param path: The path name passed to function.
        :param exc_info: The exception information return by sys.exc_info().
        """
        if func == os.unlink or func == os.remove or func == os.rmdir:
            try:
                attr = _get_permissions(path)
                if not (attr & stat.S_IWRITE):
                    os.chmod(path, stat.S_IWRITE | attr)
                    try:
                        func(path)
                    except Exception, e:
                        logger.warning("Could not delete %s: %s. Skipping", path, str(e))
                else:
                    logger.warning("Could not delete %s: Skipping", path)
            except Exception, e:
                logger.warning("Could not delete %s: %s. Skipping", path, str(e))
        else:
            logger.warning("Could not delete %s. Skipping.", path)

    if os.path.exists(path):
        try:
            if os.path.isdir(path):
                # On Windows, Python's shutil can't delete read-only files,
                # so if we were trying to delete one, remove the flag.
                # Inspired by http://stackoverflow.com/a/4829285/1074536
                logger.debug("Deleting folder with shutil.rmtree: %s", path)
                shutil.rmtree(path, onerror=_on_rm_error)
            else:
                logger.debug("Deleting file with os.remove: %s", path)
                os.remove(path)
        except Exception, e:
            logger.warning("Could not delete %s: %s", path, str(e))
    else:
        logger.warning("Could not delete: %s. Path does not exist", path)


def _do_delete_with_jstools(path):
    """
    Helper function
    """
    if os.path.exists(path):
        logger.debug("Deleting folder with jstools.jsdelete: %s", path)
        result, msg = jstools.jsdelete(path)
        if not result:
            logger.warning("Failed to delete folder with jstools.jsdelete: %s %s", path, msg)
    else:
        logger.warning("Could not delete: %s. Folder does not exist", path)


def delete_with_jstools(path):
    """
    Attempts to delete directories within the jstemplate-controlled area
    """
    dd_show = os.environ.get("DD_SHOW", None)
    if dd_show:
        template = jstools.Template(dd_show)

        # If its not a valid path, just warn the user since we'll clean it up anyway
        if not template.isValidPath(path):
            logger.warning("Path is not valid. Check your jstemplate.xml: %s", path)

        # Get the leaf path owned by the jstemplate
        leaf_path = template.getLeafPath(path)
        if leaf_path:

            # Get all children to be processed by shutil.rmtree
            for x in os.listdir(leaf_path):
                _do_delete_with_shutil_rmtree(os.path.join(leaf_path, x))

            # Now delete the rest of the path with jsdelete
            _do_delete_with_jstools(leaf_path)

        # If we've reached here, we're either somewhere in the jstemplate hierarchy
        # but not at the leaf level, or somewhere outside the jstemplate
        elif path.startswith(template.root.full_path):
            # First see if we are still in the jstemplate area
            _do_delete_with_jstools(path)
        else:
            # Finally, use shutil.rmtree to delete the non template directories
            _do_delete_with_shutil_rmtree(path)

    else:
        # Finally, use shutil.rmtree to delete the non template directories
        _do_delete_with_shutil_rmtree(path)


def _do_symlink_with_jstools(target, path):
    """
    Helper function
    """
    logger.debug("Creating symlink with jstools.jsln: %s", path)
    result, msg = jstools.jsln(target, path)
    if not result:
        raise IOError("Failed to create symlink with jstools.jsln: %s %s" % (path, msg))


def _do_symlink_with_os_symlink(target, path):
    """
    Helper function
    """
    logger.debug("Creating symlink with os.symlink: %s", path)
    try:
        os.symlink(target, path)
    except IOError, e:
        raise IOError("Failed to create symlink with os.symlink: %s %s" % (path, str(e)))


def symlink_with_jstools(target, path):
    """
    Attempts to create a symlink within the jstemplate-controlled area
    """
    dd_show = os.environ.get("DD_SHOW", None)
    if dd_show:
        template = jstools.Template(dd_show)

        # If its not a valid path, don't make it
        if not template.isValidPath(path):
            raise IOError("Path is not valid. Check your jstemplate.xml: %s" % path)

        # Get the leaf path owned by the jstemplate
        leaf_path = template.getLeafPath(path)
        if leaf_path:
            # If we're trying to create a leaf-level symlink, use jstools
            if leaf_path == path:
                _do_symlink_with_jstools(target, path)
            # Otherwise its a subdir and just use os.symlink
            else:
                _do_symlink_with_os_symlink(target, path)

        # If we've reached here, we're either somewhere in the jstemplate hierarchy
        # but not at the leaf level, or somewhere outside the jstemplate
        elif path.startswith(template.root.full_path):
            # First see if we are still in the jstemplate area
            _do_symlink_with_jstools(target, path)
        else:
            # Finally, use os.symlink to create the non template links
            _do_symlink_with_os_symlink(target, path)

    else:
        # Finally, use os.symlink to create the non template links
        _do_symlink_with_os_symlink(target, path)

def sealf_with_jstools(path):
    """
    Seal the given file/folder recursively
    i.e. prevent changing ownership and permissions.
    Use jstools to make sure we do this in a clean env.
    """
    sealf_cmd = ["sealf", "-v", "-R", path]
    result = jstools.execute(sealf_cmd)
    # result.hasFailed doesn't seem to be reliably accurate
    if result.stderr:
        logger.warning("Unable to seal file: {}\n"
                       "jstools.execute() returned code: {}".format(path, result.returnCode))
        logger.warning("stdout: {}".format(result.stdout))
        logger.warning("stderr: {}".format(result.stderr))
