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
Hook which provides advanced customization of the entity search used when
processing entities in the Template.get_entities() method.
Returns a tuple representing the updated entity search block of the form:
    (entity_type, sg_filters, sg_fields)
"""

import sgtk
HookBaseClass = sgtk.get_hook_baseclass()

class TemplateAdditionalEntities(HookBaseClass):

    def execute(self, entity_type, entity_search, sg_filters, **kwargs):
        """
        Returns an entity_search tuple containing the following:
            (entity_type, sg_filters, sg_fields)
        """
        if entity_type in ("Element", "Camera", "Cut"):
            if "Project" in entities:
                entity_search[1].extend(sg_filters)
            return entity_search

        return entity_search
