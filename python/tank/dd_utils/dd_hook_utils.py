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
"""
from jstools.execute doc string:
paraphrasing  ...the primary reason for this function's existence...the construction of an
environment initialized specifically for the new process and configured
for the current level and role

Which leads me to believe that jstools-verification will occur when dealing with disk...
"""
#  STANDARD
import os
import pdb
import shutil
import tempfile

#  DD
from dd.runtime import api
api.load('jstools')
import jstools

# SETUP LOGGING
import logging
import logging.handlers
FORMATTER = logging.Formatter('%(name)s:%(levelname)s- %(message)s')
LOGFILE = '/tmp/sgtk_log'
LOGGER = logging.getLogger('dd_hook_utils')
LOGGER.setLevel(logging.DEBUG)
# create rotating handler
ROT_HANDLER = logging.handlers.RotatingFileHandler(LOGFILE, backupCount=5)
ROT_HANDLER.setLevel(logging.DEBUG)
ROT_HANDLER.setFormatter(FORMATTER)
# create console handler
CONSOLE_HANDLER = logging.StreamHandler()
CONSOLE_HANDLER.setLevel(logging.INFO)
CONSOLE_HANDLER.setFormatter(FORMATTER)
LOGGER.addHandler(ROT_HANDLER)
LOGGER.addHandler(CONSOLE_HANDLER)


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
        jstools.jsmk(dst_path, auto=True)
    cmd_string = 'import shutil\nshutil.copy("%s", "%s")' % (src, dst)
    cmd_string_list = ['python',  '-c', cmd_string]
    result = jstools.execute(cmd_string_list)
    LOGGER.debug("jstools.execute result:%s", result)


def makedir_with_jstools(path=None):
    # pdb.set_trace()
    LOGGER.debug("makedir_with_jstools, path:%s", path)
    success, msg = jstools.jsmk(path, auto=True)  # permissions determined by jstools?

    if not success:
        print "ERROR creating directory with jsmk.  ", msg
        # TODO  - setup logging
    return success


def symlink_with_jstools(link_target=None, link_location=None):
    # pdb.set_trace()
    cmd_string = 'import os\nos.symlink(%s, %s)' % (link_target, link_location)
    cmd_string_list = ['python',  '-c', cmd_string]
    result = jstools.execute(cmd_string_list)
    LOGGER.debug("jstools.execute result:%s", result)
