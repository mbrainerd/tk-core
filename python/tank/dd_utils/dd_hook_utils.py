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
import inspect
import os
import subprocess
#  DD
from dd.runtime import api
api.load('jstools')
import jstools


# SETUP LOGGING
from ..log import LogManager
LOGGER = LogManager.get_logger(__name__)

# TODO: query for this
PROJECT_NAME = "TESTINDIA"


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


def symlink_with_jstools(link_target=None, link_location=None):
    # TODO... there is a jssymlink
    cmd_string = 'import os\nos.symlink(%s, %s)' % (link_target, link_location)
    cmd_string_list = ['python',  '-c', cmd_string]
    result = jstools.execute(cmd_string_list)
    LOGGER.debug("jstools.execute result:%s", result)


def makedir_with_jstools(path=None):
    """
    Checks path for portions 'governed'-by jstools/jstemplate
    - make directories using jstools for those portions
    - make directories using os.makedirs for the remainder
    """
    curr_frame = inspect.currentframe()
    call_frame = inspect.getouterframes(curr_frame, 2)
    LOGGER.debug("\n>>>>    makedir_with_jstools called from: %s", call_frame[1][3])
    """
    for frame, filename, line_num, func, source_code, source_index in inspect.stack():
        LOGGER.debug('\tFilename: %s\n\tLine: [%d]\n\tFunction -> %s' % (filename, line_num, func))
        frame_arg_vals = inspect.getargvalues(frame)
        for item in frame_arg_vals:
            LOGGER.debug('inspect.getargvalues(frame) - item: %s', item)
    """

    LOGGER.info("\n\nCREATE FOLDER with jstools.jsmk and/or os.makedirs, path:%s", path)

    template = jstools.Template(PROJECT_NAME)
    if template.isValidPath(path):
        # this is a jstemplate area (and the path is valid against the template)

        # leaf_path is the portion of path governed-by jsjoots
        leaf_path = template.getLeafPath(path)

        if leaf_path:  # ... or below
            # First, use jstools to create the directories up to the leaf
            success = _do_makedir_with_jstools(leaf_path)
            if success:
                LOGGER.info("\tSUCCESS creating %s", leaf_path)

                # Finally, use os.makdirs to create the remaining directories
                # .... if path is longer than leaf_path
                if path != leaf_path:
                    success = _do_makedir_with_os_makedirs(path)
                    if success:
                        LOGGER.info("\t\tSUCCESS creating %s", path)
                    else:
                        LOGGER.info("\tos.makedirs FAILED to create %s", leaf_path)
            else:
                LOGGER.info("\tjstools FAILED to create %s", leaf_path)
            return success
        else:  # above leaf
            success = _do_makedir_with_jstools(path)
            if success:
                LOGGER.info("\tSUCCESS creating %s", leaf_path)
            else:
                LOGGER.info("\tjstools FAILED to create %s", leaf_path)
    else:
        # Not in jstemplate area, or in the area but invalid jstemplate path
        # Don't want to create invalid folders in the jstemplate area, so
        LOGGER.error("Attempt to create INVALID PATH in jstemplate area: %s", path)


def _do_makedir_with_os_makedirs(path):
    """
    for some reason "os.makedirs(path, 770) was giving weird results... e.g.
        # dr------wT 2 kmohamed cgi 4.0K Jul 20 15:39 scripts/

    :param path:
    :return: bool success
    """
    LOGGER.info("\tcreating folders with OS.MAKEDIRS: %s", path)
    makedir_success = False
    try:
        os.makedirs(path)
    except OSError:
        raise

    if os.path.isdir(path):
        _cmdline_chmod(path=path, mode=770)
        makedir_success = True
    return makedir_success


def _do_makedir_with_jstools(path):
    """

    :param path:
    :return: bool success
    """
    LOGGER.info("\tcreating folders with JSTOOLS.JSMK: %s", path)
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
    LOGGER.info("chmod to %s", mode)

    cmd_string_list = ['chmod', mode, path]
    result = subprocess.call(cmd_string_list)

    result_string = "FAILED"
    if result == 0:
        result_string = "SUCCESS"
    LOGGER.debug("chmod  %s", result_string)

if __name__ == "__main__":
    test_path_0 = "/"  # OSError: [Errno 17] File exists: '/'
    test_path_1 = "/test"  # OSError: [Errno 13] Permission denied: '/test'
    test_path_2 = "/dd/testindia_test"  # OSError: [Errno 13] Permission denied: '/dd/testindia_test'
    test_path_3 = "/dd/shows/testindia_test"  # OSError: [Errno 13] Permission denied: '/dd/shows/testindia_test'
    test_path_4 = "/dd/shows/DEVTD/testindia_test"  # OSError: [Errno 13] Permission denied
    test_path_5 = "dd/shows/DEVTD/RD/0667"  #OSError: [Errno 13] Permission denied: 'dd/shows'
    test_path_6 = "dd/shows/DEVTD/RD/9999/testindia_test"  # OSError: [Errno 13] Permission denied: 'dd/shows'
    test_path_7 = "dd/shows/DEVTD/RD/9999/user"  #
    test_path_8 = ""  #
    _do_makedir_with_os_makedirs(test_path_6)
