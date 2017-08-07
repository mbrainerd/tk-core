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
from dd.runtime import api
api.load('jstools')
import jstools

from ..log import LogManager
LOGGER = LogManager.get_logger(__name__)


PROJECT_NAME = os.getenv("DD_SHOW")


def copy_using_jstools(src=None, dst=None):
    """
    jstools doesn't have a copy, so use "jstools.execute"
    """
    # check for dst_path existance
    LOGGER.debug("copy_using_jstools, pathfile: %s", dst)
    dst_path = os.path.dirname(dst)
    if not os.path.exists(dst_path):
        LOGGER.debug("%s  Doesn't exist", dst_path)
        makedir_with_jstools(dst_path)
    cmd_string = 'import shutil\nshutil.copy("%s", "%s")' % (src, dst)
    cmd_string_list = ['python',  '-c', cmd_string]
    result = jstools.execute(cmd_string_list)
    LOGGER.debug("jstools.execute result:%s", result)



def symlink_with_jstools(link_target=None, link_location=None):
    # TODO... there is a jssymlink
    cmd_string = 'import os\nos.symlink(%s, %s)' % (link_target, link_location)
    cmd_string_list = ['python',  '-c', cmd_string]
    result = jstools.execute(cmd_string_list)
    LOGGER.debug("jstools.execute result:%s", result)




def makedir_with_jstools(path=None):
    """
    Attempts to create directories AT OR BELOW jstemplate-leaf-paths
    """

    template = jstools.Template(PROJECT_NAME)
    if template.isValidPath(path):
        # valid means that "path" is IN the jstemplate area
        # and verified against the template as valid

        # this returns the leaf_path if "path" includes the leaf_path, otherwise None
        leaf_path = template.getLeafPath(path)
        LOGGER.debug("path: %s\nleaf-path: %s\n\n", path, leaf_path)
        if leaf_path:  # ... or below
            success = _do_makedir_with_jstools(path)
            if success:
                LOGGER.info("\tSUCCESS creating %s\n", path)
            else:
                LOGGER.info("\tjstools FAILED to create %s\n", path)

        else:  # above leaf
            LOGGER.info("\t%s is in jstemplate, but its not a leaf-path - SKIPPING", path)
    else:
        # Not in jstemplate area, or in the area but invalid jstemplate path
        msg = "Attempt to use jstools outside the jstemplate area OR, "
        msg += "attempt to create INVALID PATH in jstemplate area: %s" % path
        LOGGER.error(msg)


def _do_makedir_with_jstools(path):
    """
    :return: bool success
    """
    LOGGER.info("\tCreating folders with JSTOOLS.JSMK: %s", path)
    try:
        makedir_success, msg = jstools.jsmk(path)
        if not makedir_success:
            LOGGER.error("trying to create directory with jsmk. %s", msg)
    except OSError:
        raise
    if os.path.isdir(path):
        _cmdline_chmod(path=path, mode=770)
    return makedir_success


def _cmdline_chmod(path=None, mode=770):
    """
        for some reason "os.makedirs(path, 770) was giving weird results... e.g.
        # dr------wT 2 kmohamed cgi 4.0K Jul 20 15:39 scripts/

        So using subprocess instead....
    """
    LOGGER.info("chmod to %s", mode)
    cmd_string_list = ['chmod', str(mode), str(path)]

    result = subprocess.call(cmd_string_list)

    if result == 0:
        LOGGER.debug("chmod  SUCCESS")
    else:
        LOGGER.debug("chmod  FAILED")

def _do_makedir_with_jstools(path):
    LOGGER.info("\tcreating folders with JSTOOLS.JSMK: %s", path)
    success, msg = jstools.jsmk(path)
    if not success:
        LOGGER.error("trying to create directory with jsmk. %s", msg)

    LOGGER.info("chmod to 770")
    cmd_string_list = ['chmod', '770', path]
    result = subprocess.call(cmd_string_list)
    result_string = "FAILED"
    if result == 0:
        result_string = "SUCCESS"
    LOGGER.debug("chmod to '770' - result: %s", result_string)
    return success
