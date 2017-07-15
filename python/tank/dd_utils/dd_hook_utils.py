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


# SETUP LOGGING
from ..log import LogManager
LOGGER = LogManager.get_logger(__name__)



def copy_using_jstools(src=None, dst=None):
    """
    jstools doesn't have a copy, so use "jstools.execute"
    """
    # pdb.set_trace()
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


def makedir_with_jstools(path=None):
    # pdb.set_trace()
    LOGGER.info("Creating Folder with jstools.jsmk and/or os.makedirs, path:%s", path)

    template = jstools.Template("TESTINDIA")  # HARD
    if template.isValidPath(path):
        # this is a jstemplate area (and the path is valid against the template)
        leaf_path = template.getLeafPath(path)

        if leaf_path:  # ... or below
            # First, use jstools to create the directories up to the leaf
            success = _do_makedir_with_jstools(leaf_path)
            if success:
                LOGGER.info("\tSUCCESS creating %s", leaf_path)

                # Finally, use os to create the remaining directories
                result = _do_makedir_with_os_makedirs(path)
                LOGGER.info("\t_do_makedir_with_os_makedirs RETVAL: %s", result)

            return success
        else:  # above leaf
            _do_makedir_with_jstools(path)
    else:
        # Not in jstemplate area, or in the area but invalid jstemplate path
        # Don't want to create invalid folders in the jstemplate area, so
        LOGGER.error("Attempt to create INVALID PATH in jstemplate area: %s", path)


def symlink_with_jstools(link_target=None, link_location=None):
    # pdb.set_trace()
    cmd_string = 'import os\nos.symlink(%s, %s)' % (link_target, link_location)
    cmd_string_list = ['python',  '-c', cmd_string]
    result = jstools.execute(cmd_string_list)
    LOGGER.debug("jstools.execute result:%s", result)


def _do_makedir_with_os_makedirs(path):
    LOGGER.info("\tcreating folders with OS.MAKEDIRS: %s", path)
    return os.makedirs(path, 770)


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

