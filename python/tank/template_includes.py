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
include files management for template.yml

includes
----------------------------------------------------------------------
includes are defined in the following sections in the data structure:

include: path
includes: [path, path]


paths are on the following form:
----------------------------------------------------------------------
foo/bar.yml - local path, relative to current file

/foo/bar/hello.yml - absolute path, *nix
c:\foo\bar\hello.yml - absolute path, windows

"""

import os
import collections

from .errors import TankError
from . import constants
from .util import yaml_cache
from .util.includes import resolve_include

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

def _resolve_include(file_name, include):
    """
    Parse the includes section and return a list of valid paths

    :param str file_name: Name of the file to parse.
    :param aray or str data: Include path or array of include paths to evaluate.
    """
    if include.startswith("{preferences}"):
        # If this is a preferences file, just store the path
        # the Preferences system down the line with handle resolution
        resolved_include = include
    else:
        resolved_include = resolve_include(file_name, include)

    return resolved_include

def _process_template_includes_r(file_name, data):
    """
    Recursively add template include files.
    
    For each of the sections keys, strings, path, populate entries based on
    include files.
    """
    # return data    
    output_data = collections.OrderedDict()

    # normalize the incoming path
    file_name = os.path.normpath(file_name)

    # initialize the keys for paths, strings, aliases etc
    for ts in constants.TEMPLATE_SECTIONS:
        output_data[ts] = {}

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
                resolved_file = _resolve_include(file_name, include_file)
                if not resolved_file:
                    continue

                # Read the include file
                include_data = yaml_cache.g_yaml_cache.get(resolved_file, deepcopy_data=False)

                # ...process the contents
                included_data = _process_template_includes_r(resolved_file, include_data)

                # ...and merge the results
                dict_merge(output_data, included_data)

        # Now check if this is a known template section
        elif k in constants.TEMPLATE_SECTIONS:
            # Update output_data with the current file's data
            if isinstance(v, dict):
                output_data[k].update(v)
            elif v is not None:
                output_data[k] = v

        else:
            raise TankError("Unrecognized template section!")

    return output_data
        
def process_includes(file_name, data):
    """
    Processes includes for the main templates file. Will look for 
    any include data structures and transform them into real data.
    
    Algorithm (recursive):
    
    1. first load in include data into keys, strings, path sections.
       if there are multiple files, they are loaded in order.
    2. now, on top of this, load in this file's keys, strings and path defs
    3. lastly, process all @refs in the paths section
        
    """
    # first recursively load all template data from includes
    resolved_includes_data = _process_template_includes_r(file_name, data)
    
    # Now recursively process any @resolves.
    # these are of the following form:
    #   foo: bar
    #   ttt: @foo/something
    # You can only use these in the paths and strings sections.
    #
    # @ can be used anywhere in the template definition.  @ should
    # be used to escape itself if required.  e.g.:
    #   foo: bar
    #   ttt: @foo/something/@@/_@foo_
    # Would result in:
    #   bar/something/@/_bar_
    template_paths = resolved_includes_data[constants.TEMPLATE_PATH_SECTION]
    template_strings = resolved_includes_data[constants.TEMPLATE_STRING_SECTION]
    template_aliases = resolved_includes_data[constants.TEMPLATE_ALIAS_SECTION]
    
    # process the template paths section:
    for template_name, template_definition in template_paths.iteritems():
        _resolve_template_r(template_paths, 
                            template_strings, 
                            template_aliases,
                            template_name, 
                            template_definition, 
                            "path")
        
    # and process the strings section:
    for template_name, template_definition in template_strings.iteritems():
        _resolve_template_r(template_paths, 
                            template_strings,
                            template_aliases, 
                            template_name, 
                            template_definition, 
                            "string")

    # and process the strings section:
    for template_name, template_definition in template_aliases.iteritems():
        _resolve_template_r(template_paths, 
                            template_strings, 
                            template_aliases,
                            template_name, 
                            template_definition, 
                            "alias")
                
    # finally, resolve escaped @'s in template definitions:
    for templates in [template_paths, template_strings, template_aliases]:
        for template_name, template_definition in templates.iteritems():
            # find the template string from the definition:
            template_str = None
            complex_syntax = False
            if isinstance(template_definition, dict):
                template_str = template_definition.get("definition")
                complex_syntax = True
            elif isinstance(template_definition, basestring):
                template_str = template_definition
            if not template_str:
                raise TankError("Invalid template configuration for '%s' - "
                                "it looks like the definition is missing!" % (template_name))
            
            # resolve escaped @'s
            resolved_template_str = template_str.replace("@@", "@")
            if resolved_template_str == template_str:
                continue
                
            # set the value back again:
            if complex_syntax:
                templates[template_name]["definition"] = resolved_template_str
            else:
                templates[template_name] = resolved_template_str
                
    return resolved_includes_data
        
def _find_matching_ref_template(template_paths, template_strings, template_aliases, ref_string):
    """
    Find a template whose name matches a portion of ref_string.  This
    will find the longest/best match and will look at both path and string
    templates
    """
    matching_templates = []
    
    # find all templates that match the start of the ref string:
    for templates, template_type in [(template_paths, "path"), (template_strings, "string"), (template_aliases, "alias")]:
        for name, definition in templates.iteritems():
            if ref_string.startswith(name):
                matching_templates.append((name, definition, template_type))
            
    # if there are more than one then choose the one with the longest
    # name/longest match:
    best_match = None
    best_match_len = 0
    for name, definition, template_type in matching_templates:
        name_len = len(name)
        if name_len > best_match_len:
            best_match_len = name_len
            best_match = (name, definition, template_type)
            
    return best_match

def _resolve_template_r(template_paths, template_strings, template_aliases, template_name, template_definition, template_type, template_chain = None):
    """
    Recursively resolve path templates so that they are fully expanded.
    """

    # check we haven't searched this template before and keep 
    # track of the ones we have visited
    template_key = (template_name, template_type)
    visited_templates = list(template_chain or [])
    if template_key in visited_templates:
        raise TankError("A cyclic %s template was found - '%s' references itself (%s)" 
                        % (template_type, template_name, " -> ".join([name for name, _ in visited_templates[visited_templates.index(template_key):]] + [template_name])))
    visited_templates.append(template_key)
    
    # find the template string from the definition:
    template_str = None
    complex_syntax = False
    if isinstance(template_definition, dict):
        template_str = template_definition.get("definition")
        complex_syntax = True
    elif isinstance(template_definition, basestring):
        template_str = template_definition
    if not template_str:
        raise TankError("Invalid template configuration for '%s' - it looks like the "
                        "definition is missing!" % (template_name))
    
    # look for @ specified in template definition.  This can be escaped by
    # using @@ so split out escaped @'s first:
    template_str_parts = template_str.split("@@")
    resolved_template_str_parts = []
    for part in template_str_parts:
        
        # split to find seperate @ include parts:
        ref_parts = part.split("@")
        resolved_ref_parts = ref_parts[:1]
        for ref_part in ref_parts[1:]:

            if not ref_part:
                # this would have been an @ so ignore!
                continue
                
            # find a template that matches the start of the template string:                
            ref_template = _find_matching_ref_template(template_paths, template_strings, template_aliases, ref_part)
            if not ref_template:
                raise TankError("Failed to resolve template reference from '@%s' defined by "
                                "the %s template '%s'" % (ref_part, template_type, template_name))
                
            # resolve the referenced template:
            ref_template_name, ref_template_definition, ref_template_type = ref_template
            resolved_ref_str = _resolve_template_r(template_paths, 
                                                   template_strings,
                                                   template_aliases, 
                                                   ref_template_name, 
                                                   ref_template_definition, 
                                                   ref_template_type, 
                                                   visited_templates)
            resolved_ref_str = "%s%s" % (resolved_ref_str, ref_part[len(ref_template_name):])
                                    
            resolved_ref_parts.append(resolved_ref_str)
        
        # rejoin resolved parts:
        resolved_template_str_parts.append("".join(resolved_ref_parts))
        
    # re-join resolved parts with escaped @:
    resolved_template_str = "@@".join(resolved_template_str_parts)
    
    # put the value back:
    templates = {"path":template_paths, "string":template_strings, "alias":template_aliases}[template_type]
    if complex_syntax:
        templates[template_name]["definition"] = resolved_template_str
    else:
        templates[template_name] = resolved_template_str
        
    return resolved_template_str

