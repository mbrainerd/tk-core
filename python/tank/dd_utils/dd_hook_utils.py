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


def makedir_with_jstools(path=None):
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
        leaf_path = template.getLeafPath(path)

        if leaf_path:  # ... or below
            # First, use jstools to create the directories up to the leaf
            success = _do_makedir_with_jstools(leaf_path)
            if success:
                LOGGER.info("\tSUCCESS creating %s", leaf_path)

                # Finally, use os to create the remaining directories.... if path is longer than leaf_path
                if path != leaf_path:
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
    result = "Booo!"
    try:
        os.makedirs(path, 770)
    except OSError:
        raise
    if os.path.isdir(path):
        result = "SUCCESS"
    return result


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


def get_leaf_entity_from_context(context):
    """


    :param context:
    :return: dict
    """
    # get parent_entity_list from context
    parent_entity_list = context.parent_entities

    # get SG-entity leaf_levels from parent_entity_list
    # ... order matters in this for-loop - order of the parent_type's
    # .. parent_type with be ["Project"|"Sequence"|"Shot"] OR "Asset"
    leaf_levels = {}
    for parent_entity in parent_entity_list:
        parent_type = parent_entity["type"]
        if parent_type == "Project":
            leaf_levels["0"] = parent_entity
        if parent_type == "Sequence":
            leaf_levels["1"] = parent_entity
        if parent_type == "Shot":
            leaf_levels["2"] = parent_entity
        if parent_type == "Asset":
            leaf_levels["3"] = parent_entity

    # select leaf_level_entity based on MAX leaf_level-value
    selected_level = None
    parent_entity_name = None
    if leaf_levels:
        selected_level = max(leaf_levels.keys())
        # LOGGER.debug("selected_level: %s", selected_level)

        parent_entity_name = leaf_levels[selected_level]["type"]







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
