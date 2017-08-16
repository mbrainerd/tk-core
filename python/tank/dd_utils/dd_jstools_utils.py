#!/usr/bin/env python
#
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
import subprocess

#  DD
import jstools


# SETUP LOGGING
from ..log import LogManager
logger = LogManager.get_logger(__name__)


def copy_using_jstools(src=None, dst=None):
    """
    jstools doesn't have a copy, so use "jstools.execute"
    """
    # check for dst_path existance
    logger.debug("copy_using_jstools, pathfile: %s", dst)
    dst_path = os.path.dirname(dst)
    if not os.path.exists(dst_path):
        logger.debug("%s doesn't exist", dst_path)
        makedir_with_jstools(dst_path)

    cmd_string = 'import shutil\nshutil.copy("%s", "%s")' % (src, dst)
    cmd_string_list = ['python',  '-c', cmd_string]
    result = jstools.execute(cmd_string_list)
    logger.debug("jstools.execute result: %s", result)


def makedir_with_jstools(path=None, permissions=0775):
    """
    Attempts to create directories AT OR BELOW jstemplate-leaf-paths
    """
    result = 1

    dd_show = os.environ.get("DD_SHOW", None)
    if dd_show:
        template = jstools.Template(dd_show)

        # If its not a valid path, don't make it
        if not template.isValidPath(path):
            logger.error("Attempting to create INVALID PATH in jstemplate area: %s" % path)
            return 0

        # Get the leaf path owned by the jstemplate
        leaf_path = template.getLeafPath(path)
        if leaf_path:
            # Use jsmk to create the leaf-level directory
            result = _do_makedir_with_jstools(leaf_path)
            if not result:
                return result

        # If we've reached here, we're either somewhere in the jstemplate hierarchy
        # but not at the leaf level, or somewhere outside the jstemplate
        else:
            # First see if we are still in the jstemplate area
            if path.startswith(template.root.full_path):
                result = _do_makedir_with_jstools(path)
            else:
                result = _do_makedir_with_os_makedirs(path, permissions)

    else:
        # Finally, use os to create the remaining directories
        result = _do_makedir_with_os_makedirs(path, permissions)

    return result


def symlink_with_jstools(link_target=None, link_location=None):
    """
    """
    cmd_string = 'import os\nos.symlink(%s, %s)' % (link_target, link_location)
    cmd_string_list = ['python',  '-c', cmd_string]
    result = jstools.execute(cmd_string_list)
    logger.debug("jstools.execute result:%s", result)


def _do_makedir_with_os_makedirs(path, permissions):
    if os.path.isdir(path): return 1

    logger.debug("\tcreating folders with OS.MAKEDIRS: %s", path)
    return os.makedirs(path, permissions)


def _do_makedir_with_jstools(path):
    if os.path.isdir(path): return 1

    logger.debug("\tcreating folders with JSTOOLS.JSMK: %s", path)
    result, msg = jstools.jsmk(path)
    if not result:
        logger.error("Cannot jsmk folder: %s %s", path, msg)

    return result
