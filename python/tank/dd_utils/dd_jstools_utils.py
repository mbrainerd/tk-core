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


def makedir_with_jstools(path=None):
    """
    Attempts to create directories AT OR BELOW jstemplate-leaf-paths
    """

    result = 1
    template = jstools.Template(os.environ.get("DD_SHOW"))

    if template.isValidPath(path):
        # this is a jstemplate area (and the path is valid against the template)
        leaf_path = template.getLeafPath(path)

        if leaf_path:  # ... or below
            # First, use jstools to create the directories up to the leaf
            if not os.path.isdir(leaf_path):
                result = _do_makedir_with_jstools(leaf_path)
                if result:

                    # Finally, use os to create the remaining directories
                    if not os.path.isdir(path):
                        result = _do_makedir_with_os_makedirs(path)

        else:  # above leaf
            if not os.path.isdir(path):
                result = _do_makedir_with_jstools(path)
    else:
        # Not in jstemplate area, or in the area but invalid jstemplate path
        msg = "Attempting to use jstools outside the jstemplate area OR, "
        msg += "attempting to create INVALID PATH in jstemplate area: %s" % path
        logger.error(msg)
        result = 0

    return result


def symlink_with_jstools(link_target=None, link_location=None):
    """
    """
    cmd_string = 'import os\nos.symlink(%s, %s)' % (link_target, link_location)
    cmd_string_list = ['python',  '-c', cmd_string]
    result = jstools.execute(cmd_string_list)
    logger.debug("jstools.execute result:%s", result)


def _do_makedir_with_os_makedirs(path):
    logger.info("\tcreating folders with OS.MAKEDIRS: %s", path)
    return os.makedirs(path, 770)


def _do_makedir_with_jstools(path):
    logger.info("\tcreating folders with JSTOOLS.JSMK: %s", path)
    result, msg = jstools.jsmk(path, parent=True)
    if not result:
        logger.error("Cannot jsmk folder: %s %s", path, msg)

    return result
