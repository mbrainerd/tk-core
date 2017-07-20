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


# SETUP LOGGING
from ..log import LogManager
LOGGER = LogManager.get_logger(__name__)


def get_leaf_entity_from_context(context):
    """
    Collects entities from the context into "entities_by_level"
    entities_by_level = { "0": <project-entity, if present>,
                          "1": <sequence-entity, if present>,
                          "2": <shot-entity, if present>,
                          "3": <asset-entity, if present>,
                        }

    :param context: an SGTK-Context
    :return: leaf-entity
    """
    entities_by_level = {}
    leaf_entity = None
    # COLLECT entities for entities_by_level-dict from the context's "parent_entity" list
    #     * if-statement order matters in this for-loop
    for parent_entity in context["parent_entities"]:
        parent_type = parent_entity["type"]
        if parent_type == "Project":
            entities_by_level["0"] = parent_entity
        if parent_type == "Sequence":
            entities_by_level["1"] = parent_entity
        if parent_type == "Shot":
            entities_by_level["2"] = parent_entity
        if parent_type == "Asset":
            entities_by_level["3"] = parent_entity

    # SELECT SG-entity leaf_level based on MAX (existing) leaf_level-value
    if entities_by_level:
        selected_level = max(entities_by_level.keys())
        leaf_entity = entities_by_level[selected_level]

    return leaf_entity



