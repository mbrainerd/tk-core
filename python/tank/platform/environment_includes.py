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
include files management for template.yml and environment files.

includes
----------------------------------------------------------------------
includes are defined in the following sections in the data structure:

include: path
includes: [path, path]

paths are on the following form:
----------------------------------------------------------------------
foo/bar.yml - local path, relative to current file
{Sequence}/{Shot}/hello.yml - template path based on context

relative paths are always required and context based paths are always optional.

"""


import os
import re
import sys
import copy
import collections

from ..errors import TankError
from ..template import TemplatePath
from ..templatekey import StringKey
from ..log import LogManager

from . import constants

from ..util.yaml_cache import g_yaml_cache
from ..util.includes import resolve_include

log = LogManager.get_logger(__name__)

def dict_merge(dct, merge_dct):
    """ Recursive dict merge. Inspired by :meth:``dict.update()``, instead of
    updating only top-level keys, dict_merge recurses down into dicts nested
    to an arbitrary depth, updating keys. The ``merge_dct`` is merged into
    ``dct``.
    :param dct: dict onto which the merge is executed
    :param merge_dct: dct merged into dct
    :return: None
    """
    for k, v in merge_dct.iteritems():
        if (k in dct and isinstance(dct[k], dict)
                and isinstance(merge_dct[k], collections.Mapping)):
            dict_merge(dct[k], merge_dct[k])
        else:
            dct[k] = merge_dct[k]

def _resolve_include(file_name, include, context):
    """
    Parses the includes section and returns a list of valid paths
    """
    if include.startswith("{preferences}"):
        # If this is a preferences file, just store the include
        # the Preferences system down the line with handle resolution
        resolved_include = include

    elif "{" in include:
        # it's a template path
        if context is None:
            # skip - these paths are optional always
            log.debug(
                "%s: Skipping template based include '%s' "
                "because there is no active context." % (file_name, include)
            )
            return

        # extract all {tokens}
        _key_name_regex = "[a-zA-Z_ 0-9]+"
        regex = r"(?<={)%s(?=})" % _key_name_regex
        key_names = re.findall(regex, include)

        # get all the data roots for this project
        # note - it is possible that this call may raise an exception for configs
        # which don't have a primary storage defined - this is logical since such
        # configurations cannot make use of references into the file system hierarchy
        # (because no such hierarchy exists)
        primary_data_root = context.tank.pipeline_configuration.get_primary_data_root()

        # try to construct a path object for each template
        try:
            # create template key objects        
            template_keys = {}
            for key_name in key_names:
                template_keys[key_name] = StringKey(key_name, context.sgtk.pipeline_configuration)

            # Make a template
            template = TemplatePath(include,
                                    template_keys,
                                    context.sgtk.pipeline_configuration,
                                    primary_data_root)
        except TankError as e:
            raise TankError("Syntax error in %s: Could not transform include path '%s' "
                            "into a template: %s" % (file_name, include, e))

        # and turn the template into a path based on the context
        try:
            f = context.as_template_fields(template)
            resolved_include = template.apply_fields(f)
        except TankError as e:
            # if this path could not be resolved, that's ok! These paths are always optional.
            return

        if not os.path.exists(resolved_include):
            # skip - these paths are optional always
            return
    else:
        resolved_include = resolve_include(file_name, include)

    return resolved_include


def _resolve_refs_r(lookup_dict, data):
    """
    Scans data for @refs and attempts to replace based on lookup data
    """
    # default is no processing
    processed_val = data
    
    if isinstance(data, list):
        processed_val = []
        for x in data:
            processed_val.append(_resolve_refs_r(lookup_dict, x))
    
    elif isinstance(data, dict):
        processed_val = {}
        for (k, v) in data.items():
            processed_val[k] = _resolve_refs_r(lookup_dict, v)
        
    elif isinstance(data, basestring):
        # split to find separate @ include parts:
        ref_parts = data.split("@")
        processed_val = "".join(ref_parts[:1])
        for ref_part in ref_parts[1:]:

            if not ref_part:
                # this would have been an @ so ignore!
                continue

            # Check to see if we have braces surrounding our reference.
            alpha_num_string = "[a-zA-Z0-9_.-]"
            regex = "^{?(%s+)}?(\S*)" % alpha_num_string
            match = re.match(regex, ref_part)
            if not match:
                raise TankError("Failed to parse reference '@%s'" % ref_part)

            ref_name = match.group(1)
            ref_extra = match.group(2)

            # find a reference that matches the start of the ref string
            ref_definition = lookup_dict.get(ref_name)
            if ref_definition is None:
                raise TankError("Failed to resolve reference '@%s'" % ref_name)

            # other parts of the code are making changes nilly-willy to data
            # structures (ick) so flatten everything out here.... :(
            resolved_ref = copy.deepcopy(_resolve_refs_r(lookup_dict, ref_definition))

            # Cannot concatenate non-basestrings
            if not isinstance(resolved_ref, basestring):
                # If we have a string prefix or suffix
                if processed_val or ref_extra:
                    raise TankError("Cannot concatenate a string and non-string value for '%s'" % data)

                # We've evaluated the entire string value, so just return this
                return resolved_ref
            else:
                # Add back any remaining prefix and suffix
                processed_val += resolved_ref + ref_extra

    return processed_val
            
def _resolve_frameworks(lookup_dict, data):
    """
    Resolves any framework related includes
    """
    if "frameworks" in lookup_dict:
        # cool, we got some frameworks in our lookup section
        # add them to the main data

        fw = lookup_dict["frameworks"]
        if "frameworks" not in data:
            data["frameworks"] = {}
        if data["frameworks"] is None:
            data["frameworks"] = {}
        data["frameworks"].update(fw)    
    
    return data
    

def process_includes(file_name, data, context):
    """
    Process includes for an environment file.
    
    :param file_name:   The root yml file to process
    :param data:        The contents of the root yml file to process
    :param context:     The current context
    
    :returns:           The flattened yml data after all includes have
                        been recursively processed.
    """
    # call the recursive method:
    lookup_dict, _ = _process_includes_r(file_name, data, context)

    # now go through our own data, recursively, and replace any refs.
    # recurse down in dicts and lists
    try:
        data = _resolve_refs_r(lookup_dict, data)
        data = _resolve_frameworks(lookup_dict, data)
    except TankError as e:
        err_msg = "Include error. Could not resolve references for %s: %s" % (file_name, e)
        raise type(e), type(e)(err_msg), sys.exc_info()[2]

    return data
        
def _process_includes_r(file_name, data, context):
    """
    Recursively process includes for an environment file.
    
    Algorithm (recursive):
    
    1. Load include data into a big dictionary X
    2. recursively go through the current file and replace any 
       @ref with a dictionary value from X
    
    :param file_name:   The root yml file to process
    :param data:        The contents of the root yml file to process
    :param context:     The current context

    :returns:           A tuple containing the flattened yml data 
                        after all includes have been recursively processed
                        together with a lookup for frameworks to the file 
                        they were loaded from.
    """
    output_data = {}
    fw_lookup = {}

    # normalize the incoming path
    file_name = os.path.normpath(file_name)

    # basic sanity check
    if data is None:
        return output_data

    # Since the data is an OrderedDict, process the elements "in order"
    for k, v in data.iteritems():

        # first check if this is an include block
        if k in (constants.SINGLE_INCLUDE_SECTION, constants.MULTI_INCLUDE_SECTION):
            if k == constants.SINGLE_INCLUDE_SECTION:
                include_files = [v]
            else:
                include_files = v

            for include_file in include_files:
                resolved_file = _resolve_include(file_name, include_file, context)
                if not resolved_file:
                    continue

                # Read the include file
                include_data = g_yaml_cache.get(resolved_file, deepcopy_data=False)

                # ...process the contents
                included_data, included_fw_lookup = _process_includes_r(resolved_file, include_data, context)

                # ...and merge the results
                for k2, v2 in included_data.iteritems():
                    # Update output_data with the include file's data
                    if isinstance(v2, dict):
                        # Only merge the "frameworks" section
                        if k2 == "frameworks":
                            if k2 not in output_data:
                                output_data[k2] = dict()
                            dict_merge(output_data[k2], v2)
                        else:
                            output_data[k2] = v2
                    elif v2 is not None:
                        output_data[k2] = v2

                fw_lookup.update(included_fw_lookup)

            # Move on to the next key
            continue

        # If this is a frameworks section, add entries to the fw_lookup dict
        if k == "frameworks":
            # keep track of where the framework has been referenced from
            for fw_name in v.keys():
                fw_lookup[fw_name] = file_name

        # Update output_data with the current file's data
        if isinstance(v, dict):
            # Only merge the "frameworks" section
            if k == "frameworks":
                if k not in output_data:
                    output_data[k] = dict()
                dict_merge(output_data[k], v)
            else:
                output_data[k] = v
        elif v is not None:
            output_data[k] = v

    # return the processed data
    return output_data, fw_lookup
    

def find_framework_location(file_name, framework_name, context):
    """
    Find the location of the instance of a framework that will
    be used after all includes have been resolved.
    
    :param file_name:       The root yml file
    :param framework_name:  The name of the framework to find
    :param context:         The current context
    
    :returns:               The yml file that the framework is 
                            defined in or None if not found.
    """
    # load the data in for the root file:
    data = g_yaml_cache.get(file_name, context=context)

    # track root frameworks:
    root_fw_lookup = {}
    fw_data = data.get("frameworks", {})
    if fw_data and isinstance(fw_data, dict):
        for fw in fw_data.keys():
            root_fw_lookup[fw] = file_name 

    # process includes and get the lookup table for the frameworks:        
    _, fw_lookup = _process_includes_r(file_name, data, context)
    root_fw_lookup.update(fw_lookup)
    
    # return the location of the framework if we can
    return root_fw_lookup.get(framework_name) or None

    
def find_reference(file_name, context, token, absolute_location=False):
    """
    Non-recursive unless the absolute_location argument is True. Looks at all
    include files and searches for @token. Returns a tuple containing
    the file path and the token where the data can be found.

    .. note:: The absolute_location should be True or False depending on
        what it is the caller intends to do with the resulting location
        returned. In the situation where the descriptor for the bundle
        is to be updated to a new version, it is ctitical that the location
        returned by this method be the yml file and associated tokens
        housing the concrete descriptor dictionary. The goal is to ensure
        that the new descriptor contents are written to the same yml file
        where the old descriptor is defined, rather than what might be
        an included value from another yml file. A good example is how
        engines are structured in tk-config-basic, where the engine instance
        is defined in a project.yml file, but the engine's location setting
        points to an included value. In the case where absolute_location
        is True, that include will be followed and the yml file where it
        is defined will be returned. If absolute_location were False, the
        yml file where the engine instance itself is defined will be returned,
        meaning the location setting's include will not be resolved and
        followed to its source. There is the need for each of these,
        depending on the situation: when a descriptor is going to be
        updated, absolute_location should be True, and when settings other
        than the descriptor are to be queried or updated, absolute_location
        should be False. In some cases these two will return the same
        thing, but that is not guaranteed and it is entirely up to how
        the config is structured as to whether they are consistent.

    :param str file_name: The yml file to find the reference in.
    :param context: The context object to use when resolving includes.
    :param str token: The token to search for.
    :param bool absolute_location: Whether to ensure that the file path and tokens
        returned references where the given bundle's location descriptor is
        defined in full.


    :returns: Tuple containing the file path where the data was found
        and the token within the file where the data resides.
    :rtype: tuple
    """
    # load the data in 
    data = g_yaml_cache.get(file_name, context=context)
    
    found_file = None
    found_token = token

    # Since the data is an OrderedDict, process the elements "in order"
    for k, v in data.iteritems():

        # first ensure this is an include block
        if k not in (constants.SINGLE_INCLUDE_SECTION, constants.MULTI_INCLUDE_SECTION):
            continue

        if k == constants.SINGLE_INCLUDE_SECTION:
            include_files = [v]
        else:
            include_files = v

        for include_file in include_files:
            resolved_file = _resolve_include(file_name, include_file, context)
            if not resolved_file:
                continue

            # path exists, so try to read it
            included_data = g_yaml_cache.get(resolved_file, context=context)

            if token in included_data:
                # If we've been asked to ensure an absolute location, we need
                # to do some extra work, which might involve recursing up the
                # config stack until we get to a location descriptor dictionary.
                if not absolute_location:
                    # We've not been asked to resolve the absolute location, so we
                    # don't do any additional work.
                    found_file = resolved_file
                else:
                    token_data = included_data[token]
                    include_token = None

                    # If the value of the token is an include, then we can
                    # recurse up, directly referencing the include name as
                    # the new token.
                    if isinstance(token_data, basestring) and token_data.startswith("@"):
                        include_token = token_data
                    else:
                        # In the case where the data isn't itself an include,
                        # we also need to make sure that the location descriptor
                        # is itself not an include. If it is, then we still have
                        # to recurse up the stack until we find the absolute
                        # location descriptor. In that case, the location value
                        # becomes the token we're looking for.
                        if constants.ENVIRONMENT_LOCATION_KEY in included_data[token]:
                            # Check to see if there's a location descriptor. If there
                            # is then we need to check to see if that's an include.
                            location = included_data[token][constants.ENVIRONMENT_LOCATION_KEY]
                            if location and isinstance(location, basestring) and location.startswith("@"):
                                include_token = location

                    # If we have an include we need to resolve, we take the current
                    # file where we found the include, and the included name becomes
                    # the new token we're looking for.
                    if include_token is not None:
                        found_file, found_token = find_reference(
                            resolved_file,
                            context,
                            include_token[1:],
                            absolute_location=True,
                        )
                    else:
                        # We're at the top and we have the concrete location
                        # descriptor. We can return the include file and token
                        # where the data was found.
                        found_file = resolved_file
                        found_token = token

    return (found_file, found_token)
