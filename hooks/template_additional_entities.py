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
Hook which provides advanced customization of template parsing.
Returns a dict with two keys:

    entity_types_in_path: a list of Shotgun entity types (ie. CustomNonProjectEntity05) that
        context_from_path should recognize and use to fill its additional_entities list.
    
    entity_fields_on_task: a list of Shotgun fields (ie. sg_extra_link) on the Task entity
        that context_from_entity should query Shotgun for and insert the resulting entities
        into its additional_entities_list.

"""

import sgtk
HookBaseClass = sgtk.get_hook_baseclass()

class TemplateAdditionalEntities(HookBaseClass):

    def execute(self, key_name, sg_filters, query_function, **kwargs):
        """
        Returns an entity
        """
        if key_name in ["Element", "Camera", "Cut"]:
            return query_function(key_name, sg_filters)

        return query_function(key_name, [])
